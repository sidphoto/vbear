"""Terminal-title evidence for managed Claude Code sessions.

Claude Code sets the terminal title with OSC 0. While it works, the title
starts with a spinner that alternates between "◐" and "◑" about once a
second; when it stops and waits for the user, the title starts with "✳"; on
exit it clears the title. Observed for Claude Code 2.1.292 under VBear's
managed flags (docs/evidence/claude-code-2.1.292-activity.md).

The daemon feeds every chunk of a managed Claude session's output through a
``TitleTracker``. Only the classification of the title's first character is
kept. The title text itself (Claude puts a summary of the current task there)
is neither stored nor returned.

This is evidence the Agent process reports about itself: anything that can
write to the session's terminal can set a title. It is used to show whether an
Agent is working or waiting, never to decide a launch, permission or cleanup.
"""

from __future__ import annotations

WORKING_GLYPHS = frozenset("◐◑")
WAITING_GLYPHS = frozenset("✳")
MAX_OSC = 4096  # longer OSC strings are skipped, not buffered

ESC = 0x1B
BEL = 0x07
CAN = b"\x18"  # CAN and SUB cancel a control string (ECMA-48)
SUB = b"\x1a"
OSC_START = b"\x1b]"
ST_FINAL = 0x5C  # the "\" of ESC \


def classify(title: str) -> str:
    """``working`` / ``waiting`` / ``empty`` / ``other`` for one title."""
    if not title:
        return "empty"
    if title[0] in WORKING_GLYPHS:
        return "working"
    if title[0] in WAITING_GLYPHS:
        return "waiting"
    return "other"


class TitleTracker:
    """Incremental OSC parser that keeps only the latest title's class.

    ``state`` is None until the first title arrives. ``since`` is when the
    current state began and ``last_seen`` when a title in that state last
    arrived (the spinner re-sends its title while Claude works, so a stale
    ``last_seen`` in the working state means the signal stopped).
    """

    __slots__ = ("state", "since", "last_seen", "titles", "_in_osc", "_esc", "_buf", "_overflow")

    def __init__(self) -> None:
        self.state: str | None = None
        self.since: float | None = None
        self.last_seen: float | None = None
        self.titles = 0
        self._in_osc = False
        self._esc = False      # the previous chunk ended with ESC
        self._buf = bytearray()
        self._overflow = False

    def feed(self, data: bytes, now: float) -> None:
        i, n = 0, len(data)
        while i < n:
            if not self._in_osc:
                if self._esc:
                    self._esc = False
                    if data[i] == 0x5D:  # "]" right after a chunk-final ESC
                        self._start()
                        i += 1
                        continue
                j = data.find(OSC_START, i)
                if j < 0:
                    self._esc = data[n - 1] == ESC
                    return
                self._start()
                i = j + 2
                continue
            if self._esc:
                self._esc = False
                if data[i] == ST_FINAL:
                    self._finish(now)
                    i += 1
                    continue
                # ESC followed by anything else cancels the OSC; that ESC may
                # itself start the next OSC.
                self._in_osc = False
                self._esc = True
                continue
            bel = data.find(b"\x07", i)
            esc = data.find(b"\x1b", i)
            cancel = [k for k in (data.find(CAN, i), data.find(SUB, i)) if k >= 0]
            stops = [k for k in (bel, esc, *cancel) if k >= 0]
            if not stops:
                self._append(data[i:])
                return
            k = min(stops)
            self._append(data[i:k])
            if k == bel:
                self._finish(now)
                i = k + 1
            elif k in cancel:
                self._in_osc = False
                i = k + 1
            elif k + 1 >= n:
                self._esc = True
                return
            elif data[k + 1] == ST_FINAL:
                self._finish(now)
                i = k + 2
            else:
                self._in_osc = False
                i = k

    def snapshot(self) -> dict:
        return {"state": self.state, "since": self.since, "last_seen": self.last_seen,
                "titles": self.titles}

    def _start(self) -> None:
        self._in_osc = True
        self._buf = bytearray()
        self._overflow = False

    def _append(self, chunk: bytes) -> None:
        if self._overflow or not chunk:
            return
        if len(self._buf) + len(chunk) > MAX_OSC:
            self._overflow = True
            self._buf = bytearray()
            return
        self._buf += chunk

    def _finish(self, now: float) -> None:
        self._in_osc = False
        if self._overflow:
            return
        code, sep, payload = bytes(self._buf).partition(b";")
        if not sep or code not in (b"0", b"2"):
            return  # icon names, colours, notifications, hyperlinks...
        state = classify(payload.decode("utf-8", "replace"))
        if state != self.state:
            self.state = state
            self.since = now
        self.last_seen = now
        self.titles += 1
