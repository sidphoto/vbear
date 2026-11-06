"""A chat's record for a Codex chat (P38-3): chat.json version 2 with the chat's engine (a version 1 file reads as a
Claude chat), and the events a Codex chat adds (session_bound, usage, plan_usage, card_edit_sent, and the estimate and
token count of turn_ended). Synthetic HOME and VBEAR_HOME; no process is started."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from vbear.runtime import chat_store as cs

THREAD = "00000000-0000-4000-8000-000000000001"
KEY = "sk-ant-" + "fictionalfictional0123456789"          # shaped like a key, made up


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbcs-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.tmp / "st"
        self.base.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.base), "HOME": str(self.tmp / "home")})
        env.start()
        self.addCleanup(env.stop)
        self.now = time.time()

    def codex(self, profile="emp-1"):
        return cs.create(self.base, profile, now=self.now, engine="codex-chat")

    def add(self, chat_id, kind, **data):
        log = cs.ChatLog(self.base, chat_id)
        try:
            return log.append(kind, data, now=self.now)
        finally:
            log.close()

    def rewrite(self, chat_id, rec):
        path = self.base / "chats" / chat_id / "chat.json"
        path.write_text(json.dumps(rec))
        path.chmod(0o600)


class EngineTests(StoreCase):
    def test_a_codex_chat_has_an_engine_and_no_claude_session(self):
        c = self.codex()
        self.assertEqual((c["v"], c["engine"]), (2, "codex-chat"))
        self.assertNotIn("claude_session_id", c)
        self.assertEqual(cs.load(self.base, c["id"]), c)
        self.assertEqual(stat.S_IMODE(os.lstat(self.base / "chats" / c["id"] / "chat.json").st_mode), 0o600)

    def test_a_claude_chat_is_version_2_with_its_session(self):
        c = cs.create(self.base, "emp-1", now=self.now)
        self.assertEqual((c["v"], c["engine"]), (2, "claude-chat"))
        self.assertTrue(cs.UUID_RE.match(c["claude_session_id"]))
        self.assertEqual(cs.load(self.base, c["id"]), c)

    def test_a_version_1_file_reads_as_a_claude_chat(self):
        c = cs.create(self.base, "emp-1", now=self.now)
        old = {"v": 1, "id": c["id"], "profile_id": "emp-1", "created_at": self.now,
               "claude_session_id": c["claude_session_id"]}
        self.rewrite(c["id"], old)
        got = cs.load(self.base, c["id"])
        self.assertEqual((got["engine"], got["claude_session_id"], got["profile_id"]),
                         ("claude-chat", c["claude_session_id"], "emp-1"))

    def test_the_fields_are_fixed_by_the_engine(self):
        c = self.codex()
        sid = str(uuid.uuid4())
        for bad in (dict(c, claude_session_id=sid),                      # a Codex chat has no Claude session
                    dict(c, engine="grok-chat"), dict(c, engine=None), dict(c, v=3),
                    {k: v for k, v in c.items() if k != "engine"},
                    dict(c, extra=1)):
            self.rewrite(c["id"], bad)
            with self.assertRaises(cs.ChatStoreError, msg=bad):
                cs.load(self.base, c["id"])
        k = cs.create(self.base, "emp-2", now=self.now)
        for bad in ({kk: v for kk, v in k.items() if kk != "claude_session_id"}, dict(k, engine="codex-chat"),
                    dict(k, v=1), dict(k, claude_session_id="nope")):
            self.rewrite(k["id"], bad)
            with self.assertRaises(cs.ChatStoreError, msg=bad):
                cs.load(self.base, k["id"])

    def test_an_unknown_engine_cannot_be_created(self):
        for bad in ("grok-chat", "", None, "codex"):
            with self.assertRaises(cs.ChatStoreError):
                cs.create(self.base, "emp-1", now=self.now, engine=bad)
        self.assertEqual(cs.list_ids(self.base), [])


class EventTests(StoreCase):
    def test_what_a_codex_chat_adds(self):
        c = self.codex()
        self.add(c["id"], "user_message", turn=1, text="hi")
        self.add(c["id"], "turn_started", turn=1, cap_usd="0.5")
        self.add(c["id"], "session_bound", thread_id=THREAD)
        self.add(c["id"], "usage", turn=1, total_tokens=18104, delta_tokens=18104)
        self.add(c["id"], "usage", turn=1, total_tokens=20000, delta_tokens=None)
        self.add(c["id"], "plan_usage", turn=1, primary_pct=7, primary_window_min=300, primary_resets_at=1800000000,
                 secondary_pct=27, secondary_window_min=10080, secondary_resets_at=1800500000, reached=None)
        self.add(c["id"], "card_edit_sent", card_id="k-0123456789abcdef", text="run this instead: echo hi")
        end = self.add(c["id"], "turn_ended", turn=1, cost_usd="0.02", reported=False, total_usd=None,
                       reason="result", subtype="completed", is_error=False, estimate=True, tokens=18104)
        self.assertEqual((end["estimate"], end["tokens"]), (True, 18104))
        self.add(c["id"], "user_message", turn=2, text="again")
        self.add(c["id"], "turn_started", turn=2, cap_usd="0.01")
        limit = self.add(c["id"], "turn_ended", turn=2, cost_usd="0.02", reported=False, total_usd=None,
                         reason="limit", subtype="interrupted", is_error=True, estimate=True, tokens=18104)
        self.assertEqual(limit["reason"], "limit")
        ev = cs.read_events(self.base, c["id"])
        self.assertEqual(ev.problem, "")
        st = cs.derive(ev.records)
        self.assertEqual((st.thread_id, st.last_tokens), (THREAD, 20000))

    def test_a_claude_turn_end_stays_as_it_was(self):
        c = cs.create(self.base, "emp-1", now=self.now)
        self.add(c["id"], "user_message", turn=1, text="hi")
        self.add(c["id"], "turn_started", turn=1, cap_usd="0.5")
        end = self.add(c["id"], "turn_ended", turn=1, cost_usd="0.01", reported=True, total_usd=0.01, reason="result",
                       subtype="success", is_error=False)
        self.assertNotIn("estimate", end)
        self.assertNotIn("tokens", end)
        self.assertEqual(cs.read_events(self.base, c["id"]).problem, "")

    def test_a_record_that_does_not_fit_is_refused(self):
        c = self.codex()
        self.add(c["id"], "user_message", turn=1, text="hi")
        self.add(c["id"], "turn_started", turn=1, cap_usd="0.5")
        bad = [("session_bound", dict(thread_id="not-a-uuid")), ("session_bound", dict(thread_id=THREAD, extra=1)),
               ("usage", dict(turn=1, total_tokens=-1, delta_tokens=0)),
               ("usage", dict(turn=1, total_tokens=True, delta_tokens=0)),
               ("usage", dict(turn=1, total_tokens=5, delta_tokens=-3)),
               ("usage", dict(turn=1, total_tokens=5)),
               ("plan_usage", dict(turn=1, primary_pct="7", primary_window_min=300, primary_resets_at=1,
                                   secondary_pct=1, secondary_window_min=1, secondary_resets_at=1, reached=None)),
               ("plan_usage", dict(turn=1, primary_pct=7, primary_window_min=300, primary_resets_at=1,
                                   secondary_pct=1, secondary_window_min=1, secondary_resets_at=1, reached=5)),
               ("card_edit_sent", dict(card_id="nope", text="x")), ("card_edit_sent", dict(card_id="k-0123456789abcdef")),
               ("turn_ended", dict(turn=1, cost_usd="0.1", reported=False, total_usd=None, reason="result",
                                   subtype=None, is_error=False, estimate=True)),                  # one of the two only
               ("turn_ended", dict(turn=1, cost_usd="0.1", reported=False, total_usd=None, reason="result",
                                   subtype=None, is_error=False, estimate="yes", tokens=1)),
               ("turn_ended", dict(turn=1, cost_usd="0.1", reported=False, total_usd=None, reason="result",
                                   subtype=None, is_error=False, estimate=True, tokens=-1)),
               ("turn_ended", dict(turn=1, cost_usd="0.1", reported=False, total_usd=None, reason="other",
                                   subtype=None, is_error=False))]
        for kind, data in bad:
            with self.assertRaises(cs.ChatStoreError, msg=(kind, data)):
                self.add(c["id"], kind, **data)
        self.assertEqual([r["kind"] for r in cs.read_events(self.base, c["id"]).records],
                         ["chat_created", "user_message", "turn_started"])

    def test_the_text_of_a_changed_command_is_masked_and_cut(self):
        c = self.codex()
        self.add(c["id"], "user_message", turn=1, text="hi")
        self.add(c["id"], "turn_started", turn=1, cap_usd="0.5")
        rec = self.add(c["id"], "card_edit_sent", card_id="k-0123456789abcdef", text=f"use {KEY} " + "x" * 5000)
        self.assertNotIn(KEY, rec["text"])
        self.assertEqual(len(rec["text"]), cs.MAX_EXCERPT)
        self.assertNotIn(KEY, (self.base / "chats" / c["id"] / "events.jsonl").read_text())

    def test_the_last_token_total_survives_a_process(self):
        c = self.codex()
        self.add(c["id"], "user_message", turn=1, text="hi")
        self.add(c["id"], "turn_started", turn=1, cap_usd="0.5")
        self.add(c["id"], "usage", turn=1, total_tokens=100, delta_tokens=100)
        self.add(c["id"], "usage", turn=1, total_tokens=250, delta_tokens=150)
        st = cs.derive(cs.read_events(self.base, c["id"]).records)
        self.assertEqual((st.last_tokens, st.thread_id), (250, None))
        self.assertEqual(cs.derive([]).last_tokens, None)


if __name__ == "__main__":
    unittest.main()
