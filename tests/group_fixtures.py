"""P41: what the group tests share. A fake runtime daemon (the dispatch tests' ``FakeDaemon``: chats are real records in the
state folder; a turn ends when a test says so), two or three role cards, the real ``ChatService`` over it, ``Groups`` and the
``GroupRunner``. No CLI runs and nothing leaves the machine; HOME and VBEAR_HOME are synthetic and short. Every person, group name
and reply here is made up."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_dispatch_runner import FakeDaemon
from vbear import agent_profiles as ap, chat_service, group_runner, groups

HEAD = {"state": "ready"}


class GroupDaemon(FakeDaemon):
    """The dispatch tests' fake daemon, plus the removal of a chat (a group is deleted with its chats)."""

    def __init__(self, clock=time.time):
        super().__init__(clock=clock)
        self.deleted: list[str] = []
        self.delete_refuse: list[str] = []

    def _op_chat_delete(self, chat_id):
        if self.delete_refuse:
            return self._err(self.delete_refuse.pop(0))
        from vbear.runtime import chat_store as cs
        cs.delete(self._base(), chat_id, now=self.clock())
        self.deleted.append(chat_id)
        return {"ok": True, "result": {"deleted": True}}


class GroupBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbg-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        card = lambda name, position, tool="claude": ap.save_profile(None, {"name": name, "position": position, "model": {"tool": tool}})["id"]
        self.writer = card("文案小編", "social")
        self.accountant = card("會計師", "accountant")
        self.planner = card("虛構CEO", "planner")
        self.codex_hand = card("Codex會計", "accountant", "codex")
        self.now = [time.time()]
        self.daemon = GroupDaemon(clock=lambda: self.now[0])
        self.service = chat_service.ChatService(self.daemon, claude=lambda: (sys.executable, "2.1.318", ""),
                                                codex=lambda: dict(HEAD), codex_binary=lambda: (sys.executable, "0.163.0"))
        self.service.restart_pause = 0
        self.lamp = ["green"]
        self.ledger_error = [None]
        self.groups = groups.Groups(chats=lambda: self.service, ledger=self.ledger, conf=lambda: {}, clock=lambda: self.now[0])
        self.runner = group_runner.GroupRunner(self.groups, clock=lambda: self.now[0])
        self.addCleanup(self.runner.close)

    def ledger(self):
        if self.ledger_error[0] is not None:
            raise self.ledger_error[0]
        return {"lamp": self.lamp[0], "daily_usd": "3", "spent_usd": "0.5"}

    # -- helpers -------------------------------------------------------------------------------------------------------

    def make_group(self, *profile_ids, name=None):
        ids = list(profile_ids) or [self.writer, self.accountant]
        body = {"profile_ids": ids}
        if name is not None:
            body["name"] = name
        return self.groups.create(body)

    def chat_ids(self, gid):
        return {m["profile_id"]: m["chat_id"] for m in groups.load(gid)["members"]}

    def say(self, gid, text="大家好，說說各自要準備什麼", to="all"):
        return self.groups.say(gid, {"text": text, "to": to})["round"]

    def run_until_quiet(self, limit=30):
        """Ticks until a pass does nothing; returns the list of what each pass did."""
        done = []
        for _ in range(limit):
            out = self.runner.tick()
            if not out:
                return done
            done.append(out)
            if all(str(v).startswith(("waiting", "unreadable")) for v in out.values()):
                return done
        self.fail(f"the runner did not settle: {done}")

    def finish_current(self, gid, reply="這是我的回答", **kw):
        """Ends the turn that is open in the chat the round is waiting for."""
        cur = self.groups.current(gid)
        self.assertIsNotNone(cur, "no turn is open")
        self.daemon.finish(cur["chat_id"], reply=reply, **kw)
        return cur

    def simulate_turn(self, gid, pid, reply, *, reason="result", cost="0.12", is_error=False):
        """What the runner leaves after one employee answered the open round: the member's chat gets the message, the reply and the
        end of the turn (written as the daemon writes them), the group's log gets intent, sent and ended."""
        from vbear.runtime import chat_store as cs
        rec = groups.load(gid)
        member = next(m for m in rec["members"] if m["profile_id"] == pid)
        n = groups.current_round(groups.read_log(gid).records)["n"]
        base = self.groups.base()
        state = cs.derive(cs.read_events(base, member["chat_id"]).records)
        turn = state.next_turn
        log = cs.ChatLog(base, member["chat_id"])
        try:
            log.append("user_message", {"turn": turn, "text": "（群組送來的話）"}, now=self.now[0])
            log.append("turn_started", {"turn": turn, "cap_usd": "0.05"}, now=self.now[0])
            if reply is not None:
                log.append("reply", {"turn": turn, "text": reply, "truncated": False}, now=self.now[0])
            log.append("turn_ended", {"turn": turn, "cost_usd": cost, "reported": True, "total_usd": None, "reason": reason,
                                      "subtype": None, "is_error": is_error}, now=self.now[0])
        finally:
            log.close()
        with groups.log_tx(gid, lambda: self.now[0]) as tx:
            tx.append("turn_intent", round=n, profile_id=pid)
            tx.append("turn_sent", round=n, profile_id=pid, chat_id=member["chat_id"], turn=turn)
            tx.append("turn_ended", round=n, profile_id=pid, reason="result" if reason == "result" and not is_error else reason, cost_usd=cost)
        return turn

    def end_round(self, gid, how="done"):
        n = groups.current_round(groups.read_log(gid).records)["n"]
        with groups.log_tx(gid, lambda: self.now[0]) as tx:
            tx.append("round_ended", round=n, how=how)
