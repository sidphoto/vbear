"""The terminal-title checks of 「驗證這個版本」, judged from raw events.

``title_checks(events, typed_at)`` is the one judge: the interactive run
(vbear/boundary_check.py) uses it to write its report, and readers of that
report (cli_versions, claude_verify) run it again on the report's own events
instead of trusting the summary written next to them.

Events are ``[time, class]`` pairs, times in seconds since the session
started, classes as osc_title.classify() names them. Anything malformed (not
a list, a bad pair, a time that is not a finite non-negative number, a time
that goes back) fails every check with the reason; nothing raises.
"""

from __future__ import annotations

from .activity import SPINNER_STALE_S
from .numbers import finite_real

TITLE_CHECKS = ("idle_before_prompt", "working_after_prompt", "idle_after_turn", "spinner_cadence")
TITLE_CLASSES = frozenset({"working", "waiting", "empty", "other"})
_EXPECT = {
    "idle_before_prompt": "✳ before the prompt is typed",
    "working_after_prompt": "◐/◑ after the prompt",
    "idle_after_turn": "✳ again after the last working frame",
    "spinner_cadence": f"two or more working frames in a row, at most {SPINNER_STALE_S:g} s apart",
}


def _normalise(events, typed_at) -> tuple[list[tuple[float, str]], float | None, str | None]:
    """(events, typed_at, problem). On a problem the first two are empty/None."""
    typed = None
    if typed_at is not None:
        typed = finite_real(typed_at)
        if typed is None or typed < 0:
            return [], None, "送出提示的時間不是有效的數字"
    if not isinstance(events, (list, tuple)):
        return [], None, "標題事件不是清單"
    out: list[tuple[float, str]] = []
    for e in events:
        if not (isinstance(e, (list, tuple)) and len(e) == 2
                and isinstance(e[1], str) and e[1] in TITLE_CLASSES):
            return [], None, "標題事件的格式不符"
        t = finite_real(e[0])
        if t is None or t < 0:
            return [], None, "標題事件缺少有效的時間"
        if out and t < out[-1][0]:
            return [], None, "標題事件的時間倒退"
        out.append((t, e[1]))
    return out, typed, None


def title_checks(events, typed_at) -> dict:
    """The four title checks for one interactive run (times relative to start)."""
    events, typed_at, problem = _normalise(events, typed_at)
    if problem:
        return {"passed": False, "problem": problem,
                "checks": {n: {"pass": False, "expect": _EXPECT[n], "why": problem} for n in TITLE_CHECKS},
                "typed_at": None, "events": []}
    before = [s for t, s in events if typed_at is None or t < typed_at]
    after = [(t, s) for t, s in events if typed_at is not None and t >= typed_at]
    working_times = [t for t, s in after if s == "working"]
    last_working = working_times[-1] if working_times else None
    idle_after = last_working is not None and any(
        s == "waiting" and t > last_working for t, s in after)
    # Gaps between consecutive working frames inside one uninterrupted working run.
    # Only gaps over 0 count: titles from one read share a timestamp, and a
    # 0 s gap is not evidence that the spinner keeps updating. At least one
    # such gap must be measured.
    max_gap, prev, gaps = 0.0, None, 0
    for t, s in after:
        if s == "working":
            if prev is None:
                prev = t
            elif t > prev:
                max_gap = max(max_gap, t - prev)
                gaps += 1
                prev = t
        else:
            prev = None
    cadence_ok = gaps > 0 and max_gap <= SPINNER_STALE_S
    checks = {
        "idle_before_prompt": {"pass": typed_at is not None and "waiting" in before,
                               "expect": _EXPECT["idle_before_prompt"]},
        "working_after_prompt": {"pass": bool(working_times), "expect": _EXPECT["working_after_prompt"]},
        "idle_after_turn": {"pass": idle_after, "expect": _EXPECT["idle_after_turn"]},
        "spinner_cadence": {"pass": cadence_ok, "expect": _EXPECT["spinner_cadence"],
                            "max_gap_s": round(max_gap, 3) if gaps else None, "gaps": gaps,
                            **({} if gaps else {"why": "沒有觀察到持續的轉圈更新（工作中的標題少於兩個連續畫面）"})},
    }
    return {"passed": all(c["pass"] for c in checks.values()), "checks": checks,
            "typed_at": typed_at, "events": [[t, s] for t, s in events]}


def report_title_passes(data, version: str) -> bool:
    """Whether a boundary-check report shows a passing title check for
    ``version``, judged by re-running title_checks on its own events. The
    written summary must agree too (pass on all four), but never suffices."""
    if (not isinstance(data, dict) or data.get("claude_version") != version
            or data.get("passed") is not True):
        return False
    title = data.get("title")
    if not isinstance(title, dict):
        return False
    summary = title.get("checks")
    summary_ok = (title.get("passed") is True and isinstance(summary, dict)
                  and set(summary) == set(TITLE_CHECKS)
                  and all(isinstance(summary[n], dict) and summary[n].get("pass") is True for n in TITLE_CHECKS))
    return summary_ok and title_checks(title.get("events"), title.get("typed_at"))["passed"] is True
