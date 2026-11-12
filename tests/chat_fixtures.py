"""Claude Code 2.1.318 chat transcripts recorded once with the real CLI (P36-0, Haiku, an isolated temporary folder)
and de-identified by the coordinator; tests/fixtures/chat/ holds them with the opaque thinking signatures and the
login's expiry time replaced by fixed fictional values. Each line is ``{"dir": "in"|"out"|"note", "line": ...}``:
"in" is what was written to the CLI's stdin, "out" what it printed, "note" the recorder's own remark (the turn's text
and how its permission card was answered, or the end of a process).

ask:  one process, four turns (Bash ``ls -a`` allowed, Bash ``echo original`` allowed with the command changed to
      ``echo changed-by-user``, Write allowed, Read then Edit allowed), then a second process with ``--resume`` and
      one text turn. Recorded with ``--permission-prompt-tool stdio`` and ``permissions.ask: ["Bash"]``.
text: one process, recorded without ``--permission-prompt-tool stdio``: a text turn, a Bash run the CLI allowed by
      itself, a Write it refused by itself (``system/permission_denied``), another Bash run; then a resumed process
      with one text turn.

Paths are placeholders: ``/WORK`` is the work folder, ``/USER-DIR-1`` and ``/USER-DIR-2`` the account's own extra
folders that ``system/init`` reported. The session id of each transcript is replaced by ``SESSION`` here, so the fake
CLI can put in the one VBear gave it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

DIR = Path(__file__).resolve().parent / "fixtures" / "chat"
VERSION = "2.1.318"
SESSION = "SESSION"
WORK = "/WORK"


def _replace(value, old: str, new: str):
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: _replace(v, old, new) for k, v in value.items()}
    return value


def load(name: str) -> list[tuple[str, object]]:
    """[(dir, line)] of one transcript (``ask`` or ``text``), its session id replaced by SESSION."""
    rows = [json.loads(raw) for raw in (DIR / f"chat-{VERSION}-{name}.jsonl").read_text(encoding="utf-8").splitlines()]
    sid = next(r["line"]["session_id"] for r in rows if r["dir"] == "out" and isinstance(r["line"], dict)
               and r["line"].get("type") == "system" and r["line"].get("subtype") == "init")
    return [(r["dir"], _replace(r["line"], sid, SESSION)) for r in rows]


def turns(name: str) -> list[dict]:
    """The turns of a transcript in order: {"text", "policy", "out": [events the CLI printed for it, in order, with
    each control_request followed by the control_response written back ({"dir": "in", ...})]}."""
    out, cur = [], None
    for direction, line in load(name):
        if direction == "note":
            if isinstance(line, dict) and "turn" in line:
                cur = {"text": line["turn"], "policy": line["policy"], "out": []}
                out.append(cur)
            else:
                cur = None                  # the end of a process
            continue
        if cur is None:
            continue
        if direction == "in" and isinstance(line, dict) and line.get("type") == "user":
            continue
        if direction == "in" and isinstance(line, dict) and line.get("type") == "control_request":
            continue                        # the initialize request VBear writes itself
        cur["out"].append({"dir": direction, "line": line})
    return out


def events(name: str, index: int) -> list[dict]:
    """The events the CLI printed for one turn, without the answers written back."""
    return [copy.deepcopy(x["line"]) for x in turns(name)[index]["out"] if x["dir"] == "out"]


def script(name: str, index: int, *, init: dict | None = None) -> list[dict]:
    """The fake CLI's steps for one recorded turn: {"emit": [...]} for what the CLI printed and {"ask": request} for
    each permission request, after which the fake waits for VBear's answer. ``init`` replaces fields of the turn's
    system/init event (for example ``additional_directories``)."""
    steps: list[dict] = []
    for item in turns(name)[index]["out"]:
        line = copy.deepcopy(item["line"])
        if item["dir"] == "in":
            continue                        # the recorded answer; VBear writes its own
        if line.get("type") == "control_response":
            continue                        # the initialize answer; the fake writes its own
        if init and line.get("type") == "system" and line.get("subtype") == "init":
            line.update(init)
        if line.get("type") == "control_request":
            steps.append({"ask": line})
        elif steps and "emit" in steps[-1]:
            steps[-1]["emit"].append(line)
        else:
            steps.append({"emit": [line]})
    return steps


def clean_init() -> dict:
    """What system/init says with VBear's settings in force: no extra folders (P36-0 fact 8)."""
    return {"additional_directories": []}


def without_identity(text):
    """P58 (v0.25.3): a chat's system prompt now starts with the one sentence that tells the employee its name. This is what is left of ``text`` without
    it (None when nothing is), for the tests that are about the card's instructions, the memory or the shared folder. The sentence itself is tested in
    tests/test_p58_identity.py."""
    if text is None or not text.startswith("[VBear 身分] "):
        return text
    _, sep, rest = text.partition("\n\n")
    return rest if sep else None
