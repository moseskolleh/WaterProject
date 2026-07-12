"""Shared utilities: robust number parsing, rounding and formatting.

Field sheets and transcribed reports carry values such as ``078.7``
(leading zeros), ``80m`` (units appended), ``19.28M`` or ``6.5''``.
The helpers here turn those into clean floats and format numbers
consistently across figures, tables and reports.
"""

from __future__ import annotations

import math
import re
from typing import Iterable

_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_number(value, default=None) -> float | None:
    """Parse a numeric value from field data.

    Handles plain numbers, strings with leading zeros (``078.7``),
    appended units (``80m``, ``19.28M``, ``2,933lts/hr``), thousands
    separators and stray whitespace. Returns ``default`` (``None``
    unless given) when no number can be found.

    >>> parse_number("078.7")
    78.7
    >>> parse_number("0708958")
    708958.0
    >>> parse_number("19.28M")
    19.28
    >>> parse_number("2,933")
    2933.0
    >>> parse_number("") is None
    True
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    text = text.replace(",", "")
    match = _NUMBER_RE.search(text)
    if match is None:
        return default
    return float(match.group(0))


_INTERVAL_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)", re.IGNORECASE
)


def parse_depth_interval(value) -> tuple[float, float] | None:
    """Parse a depth interval such as ``0-5``, ``5 - 10`` or ``12 to 18 m``.

    Depths are unsigned; the hyphen is the range separator, never a
    minus sign. Returns ``(top, bottom)`` in metres or ``None``.
    """
    if value is None:
        return None
    match = _INTERVAL_RE.search(str(value))
    if match is None:
        return None
    top, bottom = float(match.group(1)), float(match.group(2))
    if bottom < top:
        top, bottom = bottom, top
    return top, bottom


def round_sig(value: float, sig: int = 3) -> float:
    """Round ``value`` to ``sig`` significant figures.

    >>> round_sig(2102.804, 4)
    2103.0
    >>> round_sig(0.0123456, 3)
    0.0123
    """
    if value == 0 or not math.isfinite(value):
        return value
    ndigits = sig - 1 - int(math.floor(math.log10(abs(value))))
    return round(value, ndigits)


def fmt_num(value, sig: int = 3, unit: str = "") -> str:
    """Format a number for reports with consistent significant figures.

    Integers within tolerance print without a decimal part. ``None``
    or NaN prints as an em-dash free placeholder ``n/a``.
    """
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "n/a"
    v = round_sig(float(value), sig)
    if abs(v - round(v)) < 1e-9 and abs(v) < 1e15:
        text = f"{int(round(v)):,}"
    else:
        text = f"{v:g}"
    return f"{text} {unit}".strip() if unit else text


def fmt_range(a, b, unit: str = "m", sep: str = "-") -> str:
    """Format a depth range such as ``20-30 m``."""
    return f"{fmt_num(a)}{sep}{fmt_num(b)} {unit}".strip()


def ordinal(n: int) -> str:
    """Return ``1st``, ``2nd``, ``3rd``, ``4th`` ... for ranking tables."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def strictly_increasing(values: Iterable[float]) -> bool:
    vals = list(values)
    return all(b > a for a, b in zip(vals, vals[1:]))


def clean_text(value) -> str:
    """Normalise whitespace in a text cell; empty for None."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()
