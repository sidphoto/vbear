"""Strict reading of numbers that come from data (reports, records, evidence).

Values read from JSON files or from other processes may be anything. These
helpers never raise; a value that is not a usable number reads as None, and
the caller treats that as "not verified" / "unknown".
"""

from __future__ import annotations

import math


def finite_real(value) -> float | None:
    """``value`` as a float if it is a finite real number, else None.

    bool is not a number here (``True`` would otherwise read as 1). ints too
    large for a float (``10**10000``), NaN and ±inf are refused."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None
