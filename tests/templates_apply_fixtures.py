"""P45-2: what the tests of the apply and of the undo share. A real console over a loopback server in a temporary home, the real stores of the
role cards, the skills and the routines (so what the apply makes is really made), and traps for everything an apply must never reach: the
chat service knows the role cards and nothing else, the runtime daemon is a trap, the meetings' ledger is a trap, no program may start.
Every name and text here is made up."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from tests import test_templates_api as base
from vbear import agent_profiles as ap, routines, server, skillbook, templates_builtin as tb

BUILTIN = {t["id"]: t for t in tb.builtin()}
pick, ref, tree = base.pick, base.ref, base.tree


class Crash(BaseException):
    """A console that stops in the middle of an apply: nothing in the code under test may catch it."""


class Trap:
    """Whatever is asked of it is written down and fails the test."""

    def __init__(self, label):
        self.__dict__["label"] = label
        self.__dict__["calls"] = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        self.calls.append(name)
        raise AssertionError(f"the {self.label} was asked for {name}")


class Cards:
    """The chat service of the tests: it lists the role cards (the real ones in the store, and a few fixed ones) and is asked for nothing else."""

    def __init__(self, fixed):
        self.fixed = [dict(c) for c in fixed]
        self.calls = []

    def cards(self):
        self.calls.append("cards")
        out = [dict(c) for c in self.fixed]
        for p in ap.list_profiles():
            tool = (p.get("model") or {}).get("tool")
            enabled = p.get("enabled") is not False
            out.append({"id": p["id"], "name": p["name"], "position": p.get("position"), "tool": tool, "engine": tool, "enabled": enabled,
                        "can_chat": enabled and tool in ("claude", "codex")})
        return out

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        self.calls.append(name)
        raise AssertionError(f"the chat service was asked for {name}")


def digest_of_file(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class ApplyBase(base.ApiBase):
    """ApiBase with the real stores behind the cards, and the traps."""

    def setUp(self):
        super().setUp()
        self.state = self.home / ".vbear"
        self.chats = Cards(self.chats.rows)
        self.console.chats = self.chats
        self.runtime = Trap("runtime daemon")
        self.console.runtime = self.runtime
        for target in (mock.patch.object(server.Console, "meeting_runner", side_effect=AssertionError("the meetings' ledger was asked")),
                       mock.patch("threading.excepthook", lambda args: None)):
            target.start()
            self.addCleanup(target.stop)
        # the files an apply must never touch, with something in them
        self.watched = {
            "config.json": b'{"port": 7791, "chat_limits": {"per_turn_usd": 0.05}}\n',
            "memory/memory.json": b'{"v": 1, "lines": [], "cards_off": [], "cards_on": []}\n',
            "shared-meta/state.json": b'{"cards_on": []}\n',
        }
        for relative, content in self.watched.items():
            path = self.state / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.before_watched = self.read_watched()

    # -- the world ---------------------------------------------------------------------------------------------------

    def read_watched(self):
        out = {}
        for relative in self.watched:
            out[relative] = (self.state / relative).read_bytes() if (self.state / relative).exists() else None
        return out

    def assert_watched_unchanged(self):
        self.assertEqual(self.read_watched(), self.before_watched, "config.json, the memory and the shared folder's switches are what they were")

    def stored_cards(self):
        return {p["id"]: p for p in ap.list_profiles()}

    def stored_skills(self):
        return {s["id"]: s for s in skillbook.view()["skills"]}

    def stored_routines(self):
        return {r["id"]: r for r in routines.read_routines()[0]}

    def nothing_made(self):
        self.assertEqual((self.stored_cards(), self.stored_skills(), self.stored_routines()), ({}, {}, {}))
        self.assertFalse((self.state / "templates").exists(), "not even a record")

    def assert_no_ai_no_chat_no_ledger(self):
        self.assertEqual(set(self.chats.calls) - {"cards"}, set(), "the chat service was only asked for the cards")
        self.assertEqual(self.runtime.calls, [], "the daemon was not asked")

    # -- calls -------------------------------------------------------------------------------------------------------

    def apply(self, body, **kw):
        return self.call("/api/templates/apply", "POST", body, **kw)

    def apply_crash(self, body):
        """An apply during which the console stops: the connection just goes away."""
        try:
            self.apply(body)
        except Exception:
            return None

    def applies(self):
        return self.call("/api/templates")[1]["applies"]

    def undo_preview(self, apply_id, body=None, **kw):
        return self.call(f"/api/templates/applies/{apply_id}/undo-preview", "POST", {} if body is None else body, **kw)

    def undo(self, apply_id, ids, **kw):
        return self.call(f"/api/templates/applies/{apply_id}/undo", "POST", {"delete": list(ids)}, **kw)

    def everything_of(self, tool="claude", templates=("shop", "creator", "studio", "life")):
        cards = [pick(t, c["key"]) for t in templates for c in BUILTIN[t]["cards"]]
        skills = [pick(t, s["key"]) for t in templates for s in BUILTIN[t]["skills"]]
        rows = [pick(t, r["key"]) for t in templates for r in BUILTIN[t]["routines"]]
        return {"tool": tool, "cards": cards, "skills": skills, "routines": rows}

    def small_pick(self, tool="claude"):
        """Two employees, two skills and two routines of 小店; each routine goes to a ticked employee."""
        return {"tool": tool, "cards": [pick("shop", "copy"), pick("shop", "accounting")], "skills": [pick("shop", "product"), pick("shop", "daybook")],
                "routines": [pick("shop", "promo"), pick("shop", "spend")]}

    def make_small(self, tool="claude"):
        status, out = self.apply(self.small_pick(tool))
        self.assertEqual(status, 201, out)
        return out["apply"]

    def ids_of(self, apply, kind):
        return [i["id"] for i in apply["items"] if i["kind"] == kind and i["state"] == "made"]

    def id_named(self, kind, name):
        rows = {"card": self.stored_cards(), "skill": self.stored_skills(), "routine": self.stored_routines()}[kind]
        found = [i for i, r in rows.items() if r["name"] == name]
        self.assertEqual(len(found), 1, name)
        return found[0]

    def put(self, relative, content="{}"):
        path = self.state / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        return path
