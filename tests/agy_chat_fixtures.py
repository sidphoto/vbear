"""Synthetic ``agy acp`` 1.5.3 transcripts (P46-1); tests/fixtures/agy-chat/ holds them.

They are NOT recordings: the spike of 2026-11-09 kept no raw messages. Each file's first line is
``{"_synthetic": "...", "defaults": {...}}`` and says so; the rest is built from the facts of runs/20261109-p46/plan.md
("實測事實", "ACP 訊息") and the public ACP v1 message formats. The first real run of ``boundary_check --mode agy-chat``
confirms every field (docs/evidence/agy-1.5.3-chat.md section 11). Every name, id, command and text is made up; the made-up
plan name, sign-in method and skill names in the handshake are there to prove VBear keeps none of them (``SENSITIVE``).

A file is a script, one row per line:

  {"dir": "in", "method": "session/prompt"}     wait for VBear to write a line with this method
  {"dir": "out", "line": {...}}                 print this line
  {"dir": "answer", "allow": [rows], "deny": [rows], "cancelled": [rows], "error": [rows], "other": [rows]}
                                                wait for VBear's answer to the request printed last; play the branch of the
                                                answer it gave (the option it chose is looked up in that request's options)
  {"include": "_handshake-new"}                 the rows of another file (a file whose name starts with "_" is only a partial)

Values: a string that is exactly ``$NAME`` is replaced by the variable (any JSON type), ``${NAME}`` inside a string by its text.
The variables are the header's ``defaults``, then ``vars`` of the player; ``WORK`` and ``SHARED`` are what VBear named, ``SESSION``
is the session id, ``REPLY`` the id of the line matched last, ``PROMPT`` the id of the last ``session/prompt``, ``REQ`` a new id for a
request of the agent. ``Player`` plays a script in memory (the tracker's tests); tests/fake_agy_acp.py plays it over stdio.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shlex
import sys
from collections import deque
from pathlib import Path

DIR = Path(__file__).resolve().parent / "fixtures" / "agy-chat"
VERSION = "1.5.3"
MODEL = "gemini-3.8-flash-high"
SESSION = "00000000-0000-4000-8000-0000000000a1"
OTHER_SESSION = "00000000-0000-4000-8000-0000000000b2"

# The made-up values the handshake carries and VBear must keep none of (the plan's name, the sign-in methods, the skill names).
SENSITIVE = ("fake-tier-alpha", "fake-auth-1", "Made-up sign-in", "fake-skill-alpha", "fake-skill-beta", "authMethods", "tier")

_VAR = re.compile(r"^\$([A-Z][A-Z_]*)\Z")
_INLINE = re.compile(r"\$\{([A-Z][A-Z_]*)\}")


def names() -> list[str]:
    """The scripts a test may play (the partials, whose names start with an underscore, are not among them)."""
    return sorted(p.stem for p in DIR.glob("*.jsonl") if not p.name.startswith("_"))


def _read(name: str) -> tuple[dict, list]:
    rows = [json.loads(raw) for raw in (DIR / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if raw.strip()]
    header, body = rows[0], rows[1:]
    if not (isinstance(header, dict) and isinstance(header.get("_synthetic"), str) and header["_synthetic"]):
        raise ValueError(f"{name}: the first line must say the file is synthetic")
    return header, body


def load(name: str) -> tuple[dict, list]:
    """(the variables' defaults, the rows) of a script with its includes spread out. A file's own defaults win over its includes'."""
    header, body = _read(name)
    defaults: dict = {}
    rows: list = []
    for row in body:
        if "include" in row:
            inner_defaults, inner_rows = load(row["include"])
            for key, value in inner_defaults.items():
                defaults.setdefault(key, value)
            rows += inner_rows
        else:
            rows.append(row)
    defaults.update(header.get("defaults", {}))
    return defaults, rows


def is_response(line) -> bool:
    return isinstance(line, dict) and "id" in line and "method" not in line


def is_request(line) -> bool:
    return isinstance(line, dict) and "id" in line and "method" in line


class Player:
    """One script in memory: ``send(line)`` is what VBear writes, the result is what the agent prints because of it (and
    ``initial``, what it printed before VBear wrote anything). The player stops at a request of the agent until the answer comes.
    Anything VBear writes that the script does not expect is kept in ``unexpected`` (a request among them is answered with an error)."""

    def __init__(self, name: str, vars: dict | None = None, *, work: str = "/made/up/work", shared: str | None = None):
        defaults, rows = load(name)
        self.name = name
        self.vars: dict = {"WORK": work, "SHARED": shared, "SESSION": SESSION, "MODEL": MODEL, **defaults, **(vars or {})}
        self.queue: deque = deque(rows)
        self.seen: list = []                 # every line VBear wrote
        self.unexpected: list = []           # (why, line)
        self.choices: list = []              # (decision, optionId, kind) of every answer to a request of the agent
        self.awaiting: dict | None = None    # the request the agent printed last: {"id", "options"}
        self._reply = self._prompt = None
        self._next_req = 1
        self.initial = self._run()

    # -- values

    def _lookup(self, key: str):
        if key == "REPLY":
            return self._reply
        if key == "PROMPT":
            return self._prompt
        if key == "REQ":
            self._next_req += 1
            return self._next_req - 1
        if key not in self.vars:
            raise KeyError(f"{self.name}: no variable {key}")
        return self.vars[key]

    def _sub(self, value, depth: int = 0):
        if depth > 8:
            raise ValueError("variables refer to each other too deeply")
        if isinstance(value, str):
            m = _VAR.match(value)
            if m:
                return self._sub(copy.deepcopy(self._lookup(m.group(1))), depth + 1)
            return _INLINE.sub(lambda mm: str(self._sub(self._lookup(mm.group(1)), depth + 1)), value)
        if isinstance(value, list):
            return [self._sub(v, depth + 1) for v in value]
        if isinstance(value, dict):
            return {k: self._sub(v, depth + 1) for k, v in value.items()}
        return value

    # -- playing

    def _run(self) -> list:
        outs = []
        while self.queue and self.queue[0]["dir"] == "out":
            line = self._sub(self.queue.popleft()["line"])
            if is_request(line):
                params = line.get("params")
                self.awaiting = {"id": line["id"], "options": params.get("options") if isinstance(params, dict) else None}
            outs.append(line)
        return outs

    def _classify(self, msg: dict) -> str:
        if "error" in msg:
            return "error"
        outcome = (msg.get("result") or {}).get("outcome") if isinstance(msg.get("result"), dict) else None
        if not isinstance(outcome, dict):
            return "other"
        if outcome.get("outcome") == "cancelled":
            self.choices.append(("cancelled", None, None))
            return "cancelled"
        chosen = outcome.get("optionId")
        kind = next((o.get("kind") for o in (self.awaiting or {}).get("options") or [] if isinstance(o, dict)
                     and o.get("optionId") == chosen), None)
        decision = {"allow_once": "allow", "reject_once": "deny"}.get(kind, "other")
        self.choices.append((decision, chosen, kind))
        return decision

    def send(self, line) -> list:
        msg = json.loads(line) if isinstance(line, (bytes, str)) else line
        self.seen.append(msg)
        if isinstance(msg, dict):
            for key in ("session/new", "session/resume"):
                if msg.get("method") == key and isinstance((msg.get("params") or {}).get("cwd"), str):
                    self.vars["WORK"] = msg["params"]["cwd"]
        head = self.queue[0] if self.queue else None
        if head and head["dir"] == "in" and isinstance(msg, dict) and msg.get("method") == head["method"]:
            self.queue.popleft()
            if "id" in msg:
                self._reply = msg["id"]
                if msg["method"] == "session/prompt":
                    self._prompt = msg["id"]
            return self._run()
        if head and head["dir"] == "answer" and is_response(msg) and self.awaiting and msg["id"] == self.awaiting["id"]:
            decision = self._classify(msg)
            self.queue.popleft()
            branch = head.get(decision)
            if branch is None:
                self.unexpected.append((f"no branch for the answer {decision}", msg))
                branch = head.get("other") or []
            self.queue.extendleft(reversed(copy.deepcopy(branch)))
            self.awaiting = None
            return self._run()
        self.unexpected.append((f"expected {head['dir'] + ' ' + str(head.get('method', '')) if head else 'nothing'}", msg))
        if is_request(msg):
            return [{"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not part of the script"}}]
        return []

    @property
    def finished(self) -> bool:
        return not self.queue


def write_launcher(path, config_path) -> str:
    """An executable named by ``path`` that runs tests/fake_agy_acp.py with ``config_path`` as its configuration. The daemon gives a chat
    process a fixed environment, so the configuration cannot be found through HOME. The launcher replaces itself with the Python
    process (``exec``), so that the process list shows tests/fake_agy_acp.py: a process a test left behind can be found by that name."""
    repo = Path(__file__).resolve().parent.parent
    body = (f"#!/bin/sh\nFAKE_AGY_CONFIG={shlex.quote(str(config_path))} exec {shlex.quote(sys.executable)} -I "
            f"{shlex.quote(str(repo / 'tests' / 'fake_agy_acp.py'))} \"$@\"\n")
    Path(path).write_text(body, encoding="utf-8")
    os.chmod(path, 0o755)
    return str(path)
