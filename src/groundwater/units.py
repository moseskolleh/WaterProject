"""Unit strings as field sheets and laboratories actually write them.

Every number this toolkit reads arrives beside a unit written by hand, and
until now those units were decoration: a laboratory result was compared
against a guideline value whatever unit each carried, and a pumping test's
discharge was taken as cubic metres per hour whatever the sheet said. Both
are silent, order-of-magnitude errors. An arsenic result of 5 reported in
ug/L is a quarter of the WHO guideline; read as mg/L it is five hundred
times over it, and the same arithmetic run the other way certifies unsafe
water as safe. A discharge of 2 L/s read as 2 m3/h understates the yield by
a factor of 1.8.

So units are parsed, not assumed. Each recognised spelling maps onto a
:class:`Unit` carrying a dimension and a factor to that dimension's base,
and two quantities are comparable only when their dimensions agree. A
spelling this module does not recognise is *not* guessed at: the caller is
told it could not be read, and the toolkit reports the value as
indeterminate rather than grading it against a limit it may not share a
scale with.

Bases: concentration mg/L, conductivity uS/cm, turbidity NTU, microbial
CFU/100 mL, flow m3/h, time min, length m.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .utils import parse_number

__all__ = [
    "Unit",
    "Quantity",
    "parse_unit",
    "convert",
    "comparable",
    "canonical_unit",
    "unit_from_label",
    "read_quantity",
    "AMBIGUOUS_UNITS",
    "CANONICAL_UNITS",
]


@dataclass(frozen=True)
class Unit:
    """A recognised unit and how to reach its dimension's base unit.

    ``value_in_base = value * factor + offset``. ``basis`` records a
    chemical reference the unit itself names ("as CaCO3", "as N"); two
    units that both name a basis are comparable only when it is the same
    one, because 10 mg/L as N and 10 mg/L as NO3 are different waters.
    """

    canonical: str
    dimension: str
    factor: float
    offset: float = 0.0
    basis: str = ""


#: Spellings that name a real quantity but do not pin it down. Guessing at
#: one of these is exactly the failure this module exists to prevent, so
#: they are refused by name and the message says why.
AMBIGUOUS_UNITS = {
    "gpm": "gallons per minute is ambiguous (US gallon 3.785 L, imperial 4.546 L)",
    "gph": "gallons per hour is ambiguous (US gallon 3.785 L, imperial 4.546 L)",
    "gal/min": "gallons per minute is ambiguous (US gallon 3.785 L, imperial 4.546 L)",
    "gal/h": "gallons per hour is ambiguous (US gallon 3.785 L, imperial 4.546 L)",
    "ppt": "ppt means parts per thousand to some laboratories and parts per "
           "trillion to others",
    "jtu": "Jackson turbidity units are not numerically interchangeable with NTU",
}

# Superscripts and micro signs as spreadsheets, PDFs and handwriting produce
# them. Normalised away before anything is matched.
_CHAR_FIXES = {
    "µ": "u",  # MICRO SIGN
    "μ": "u",  # GREEK SMALL LETTER MU
    "³": "3",  # SUPERSCRIPT THREE
    "²": "2",
    "°": "deg ",
    "⁄": "/",  # FRACTION SLASH
    "’": "",
}

_BASIS_RE = re.compile(r"\bas\s+([a-z0-9()\.\-]+)\s*$")


def _normalise(text: str) -> str:
    """Lowercase and regularise a written unit before matching it."""
    s = str(text or "")
    for bad, good in _CHAR_FIXES.items():
        s = s.replace(bad, good)
    s = s.lower().strip()
    s = s.replace("–", "-").replace("—", "-")
    # "per" written out, and the odd "l per s"
    s = re.sub(r"\bper\b", "/", s)
    # spelled-out units, longest first so "minutes" does not become "min utes"
    s = re.sub(r"\bmilli\s*litres?\b|\bmilli\s*liters?\b|\bmillilitres?\b"
               r"|\bmilliliters?\b", "ml", s)
    s = re.sub(r"\blitres?\b|\bliters?\b", "l", s)
    s = re.sub(r"\bmetres?\b|\bmeters?\b", "m", s)
    s = re.sub(r"\bcubic\s*m\b", "m3", s)
    s = re.sub(r"\bminutes?\b|\bmins\b", "min", s)
    s = re.sub(r"\bseconds?\b|\bsecs\b", "s", s)
    s = re.sub(r"\bhours?\b|\bhrs\b", "h", s)
    s = re.sub(r"\bdays?\b", "d", s)
    s = re.sub(r"\bdegrees?\b|\bdeg\b", "deg ", s)
    s = re.sub(r"\bcelsius\b|\bcentigrade\b", "c", s)
    s = s.replace(".", "")
    # "-", "n/a" and friends are how a sheet writes "no unit here", not a
    # unit. Reading "-" as pH units made every non-pH row carrying the
    # ordinary blank marker unevaluable.
    if s in ("-", "--", "n/a", "na", "none", "nil", "?"):
        return ""
    # collapse whitespace, and drop it around a solidus so "mg / l" == "mg/l"
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*/\s*", "/", s)
    return s


def _split_basis(text: str) -> tuple[str, str]:
    """Separate a trailing chemical basis: "mg/l as caco3" -> ("mg/l", "caco3")."""
    match = _BASIS_RE.search(text)
    if not match:
        return text, ""
    return text[: match.start()].strip(), match.group(1).replace(" ", "")


# (dimension, factor to base, offset), keyed by normalised spelling.
_UNITS: dict[str, tuple[str, str, float, float]] = {}


def _register(canonical: str, dimension: str, factor: float,
              spellings: list[str], offset: float = 0.0) -> None:
    for spelling in spellings:
        _UNITS[_normalise(spelling)] = (canonical, dimension, factor, offset)


# --- concentration, base mg/L ------------------------------------------------
_register("mg/L", "concentration", 1.0,
          ["mg/l", "mg/L", "milligrams/l", "mg per l", "mg/dm3", "ppm",
           "parts per million", "g/m3"])
_register("ug/L", "concentration", 1e-3,
          ["ug/l", "µg/l", "μg/l", "mcg/l", "ppb",
           "parts per billion", "mg/m3"])
_register("ng/L", "concentration", 1e-6, ["ng/l", "ppt-mass-ng"])
_register("g/L", "concentration", 1e3, ["g/l", "g/dm3", "kg/m3"])
_register("mg/mL", "concentration", 1e3, ["mg/ml"])

# --- electrical conductivity, base uS/cm ------------------------------------
_register("uS/cm", "conductivity", 1.0,
          ["us/cm", "µs/cm", "μs/cm", "umho/cm", "umhos/cm",
           "micro siemens/cm"])
_register("mS/cm", "conductivity", 1e3, ["ms/cm", "mmho/cm", "mmhos/cm"])
_register("mS/m", "conductivity", 10.0, ["ms/m"])
_register("S/m", "conductivity", 1e4, ["s/m"])

# --- turbidity, base NTU ----------------------------------------------------
# NTU, FNU and FTU are numerically interchangeable by convention; JTU is not,
# and is refused above rather than converted.
_register("NTU", "turbidity", 1.0, ["ntu", "fnu", "ftu", "nephelometric"])

# --- microbiological, base CFU/100 mL ---------------------------------------
_register("CFU/100 mL", "microbial", 1.0,
          ["cfu/100ml", "cfu/100 ml", "mpn/100ml", "mpn/100 ml", "/100ml",
           "count/100ml", "counts/100ml", "no/100ml", "cfu/100cm3"])
_register("CFU/mL", "microbial", 100.0, ["cfu/ml", "mpn/ml", "count/ml"])
_register("CFU/L", "microbial", 0.1, ["cfu/l", "mpn/l", "count/l"])

# --- pH ---------------------------------------------------------------------
_register("pH units", "ph", 1.0, ["ph units", "ph unit", "ph", "su",
                                  "standard units"])

# --- temperature, base deg C ------------------------------------------------
_register("deg C", "temperature", 1.0, ["deg c", "c", "°c", "degc",
                                        "celsius"])
_register("deg F", "temperature", 5.0 / 9.0, ["deg f", "f", "°f", "degf"],
          offset=-32.0 * 5.0 / 9.0)

# --- volumetric flow, base m3/h ---------------------------------------------
_register("m3/h", "flow", 1.0,
          ["m3/h", "m3/hr", "m³/h", "cum/h", "cubic m/h", "m3 h-1"])
_register("m3/d", "flow", 1.0 / 24.0, ["m3/d", "m3/day", "cum/d"])
_register("m3/min", "flow", 60.0, ["m3/min"])
_register("m3/s", "flow", 3600.0, ["m3/s"])
_register("L/s", "flow", 3.6, ["l/s", "lps", "l s-1"])
_register("L/min", "flow", 0.06, ["l/min", "lpm", "l/m"])
_register("L/h", "flow", 1e-3, ["l/h", "lph"])
_register("L/d", "flow", 1e-3 / 24.0, ["l/d", "l/day"])

# --- time, base minutes -----------------------------------------------------
_register("min", "time", 1.0, ["min", "mins", "minute"])
_register("s", "time", 1.0 / 60.0, ["s", "sec"])
_register("h", "time", 60.0, ["h", "hr"])
_register("d", "time", 1440.0, ["d", "day"])

# --- length, base metres ----------------------------------------------------
_register("m", "length", 1.0, ["m", "metre"])
_register("cm", "length", 0.01, ["cm"])
_register("mm", "length", 1e-3, ["mm"])
_register("ft", "length", 0.3048, ["ft", "feet", "foot"])
_register("in", "length", 0.0254, ["in", "inch", "inches", '"'])

#: Dimensions where a bare "m", "s" or "d" is meant as this dimension. A unit
#: string alone cannot tell metres from minutes-of-arc; the caller says which
#: family it is reading, so "m" in a depth column is length and "min" in a
#: time column is time.
_DIMENSION_HINT_OVERRIDES = {
    ("time", "m"): ("min", "time", 1.0, 0.0),
    ("time", "min"): ("min", "time", 1.0, 0.0),
    ("length", "m"): ("m", "length", 1.0, 0.0),
    ("concentration", "-"): None,
}


def parse_unit(text: str, *, dimension: str | None = None) -> Optional[Unit]:
    """Read a written unit, or ``None`` when it cannot be read with confidence.

    ``dimension`` disambiguates spellings that mean different things in
    different columns - a bare "m" is metres in a depth column and minutes
    in a time column - and, when given, also rejects a unit belonging to
    another family outright.
    """
    normalised = _normalise(text)
    if not normalised:
        return None
    body, basis = _split_basis(normalised)
    if body in AMBIGUOUS_UNITS or normalised in AMBIGUOUS_UNITS:
        return None

    if dimension is not None:
        override = _DIMENSION_HINT_OVERRIDES.get((dimension, body))
        if override is not None:
            canonical, dim, factor, offset = override
            return Unit(canonical, dim, factor, offset, basis)

    entry = _UNITS.get(body)
    if entry is None:
        return None
    canonical, dim, factor, offset = entry
    if dimension is not None and dim != dimension:
        return None
    return Unit(canonical, dim, factor, offset, basis)


def canonical_unit(text: str, *, dimension: str | None = None) -> str:
    """The canonical spelling of a unit, or the text as written if unknown."""
    unit = parse_unit(text, dimension=dimension)
    return unit.canonical if unit is not None else str(text or "").strip()


def comparable(a: Unit | None, b: Unit | None) -> bool:
    """Whether two parsed units measure the same thing on the same basis.

    A basis stated on one side only is accepted: a laboratory writing plain
    "mg/L" for hardness against a "mg/L as CaCO3" guideline means the same
    thing, and the parameter name already carries the reference. Two
    *different* stated bases are refused, because "as N" and "as NO3" are
    not the same number.
    """
    if a is None or b is None:
        return False
    if a.dimension != b.dimension:
        return False
    if a.basis and b.basis and a.basis != b.basis:
        return False
    return True


#: The unit each dimension is stored in once a sheet has been read. Field
#: names elsewhere in the package encode these - ``discharge_m3_per_h``,
#: ``time_min`` - so they are the contract, not a preference.
CANONICAL_UNITS = {
    "concentration": "mg/L",
    "conductivity": "uS/cm",
    "turbidity": "NTU",
    "microbial": "CFU/100 mL",
    "ph": "pH units",
    "temperature": "deg C",
    "flow": "m3/h",
    "time": "min",
    "length": "m",
}

# A unit written on a field sheet appears in brackets: "Time (min)",
# "Discharge per step (m3/h)", "Q [L/s]". Only bracketed text is treated as a
# declared unit, so an ordinary word in a label ("Discharge per step") is
# never mistaken for one and never reported as unreadable.
_BRACKETED_RE = re.compile(r"[(\[]([^)\]]{1,20})[)\]]")
_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


@dataclass(frozen=True)
class Quantity:
    """A number read off a sheet together with what its unit turned out to be.

    ``value`` is in the dimension's canonical unit and is ``None`` whenever
    the reading must not be used - an unrecognised unit is refused, never
    guessed at. ``status`` is one of:

    ``"absent"``
        no number in the cell at all.
    ``"ok"``
        a unit was declared and it is already the canonical one.
    ``"converted"``
        a unit was declared and the value has been scaled onto the canonical
        one; ``unit_text`` says which.
    ``"assumed"``
        no unit was declared anywhere, so the canonical one was assumed.
    ``"unknown"``
        a unit was declared and could not be read. ``value`` is ``None``.
    """

    value: Optional[float]
    raw_value: Optional[float]
    unit_text: str
    status: str
    dimension: str = ""

    @property
    def ok(self) -> bool:
        return self.value is not None


def unit_from_label(text: str, *, dimension: str) -> tuple[str, Optional[Unit]]:
    """The unit a column header or row label declares, if any.

    Returns ``(written, parsed)``. ``("", None)`` means nothing was declared;
    ``("L/s", Unit(...))`` means it was declared and read; ``("furlongs",
    None)`` means it was declared and could not be read, which the caller
    must treat as a refusal rather than a default.
    """
    raw = str(text or "")
    first_written = ""
    for match in _BRACKETED_RE.finditer(raw):
        candidate = match.group(1).strip()
        if not candidate:
            continue
        # "(0-60 min)" and "(step or constant)" are prose, not units
        if len(candidate.split()) > 2 or _NUMBER_RE.fullmatch(candidate):
            continue
        unit = parse_unit(candidate, dimension=dimension)
        if unit is not None:
            return candidate, unit
        if not first_written:
            first_written = candidate
    return first_written, None


# A unit beside a number is a short token: "L/s", "m3/h", "min". Anything
# longer, or with a space inside, or with no letter in it, is a field
# annotation - "5 (pump off)", "12 pump stopped", "5*" - and reading one as a
# unit refused the reading and, for a time column, dropped the whole series.
_CELL_UNIT_RE = re.compile(r"^[a-z0-9/\u00b3\u00b2^-]{1,12}$")


def _unit_in_cell(cell) -> str:
    """Any unit written next to the number inside a value cell itself.

    A crew that types "0.81 L/s" into a column headed m3/h means L/s, so the
    cell outranks its header. A note written beside the reading is not a
    unit and is ignored, so the header still speaks for the column.
    """
    if cell is None or isinstance(cell, (int, float)):
        return ""
    text = str(cell).strip().replace(",", "")
    match = _NUMBER_RE.search(text)
    if match is None:
        return ""
    tail = (text[: match.start()] + " " + text[match.end():]).strip()
    tail = tail.strip("()[]:= \t")
    if not tail:
        return ""
    normalised = _normalise(tail)
    if not normalised or not _CELL_UNIT_RE.match(normalised):
        return ""
    if not any(ch.isalpha() for ch in normalised):
        return ""
    return tail


def read_quantity(cell, *hints: str, dimension: str) -> Quantity:
    """Read a value off a sheet and put it in the canonical unit.

    The unit is taken from the cell's own text first, then from each hint in
    turn - typically the column header, then the row label. ``hints`` are
    scanned with :func:`unit_from_label`, so only bracketed text counts.
    """
    canonical = CANONICAL_UNITS[dimension]
    raw = parse_number(cell)
    if raw is None:
        return Quantity(None, None, "", "absent", dimension)

    written = _unit_in_cell(cell)
    if written:
        unit = parse_unit(written, dimension=dimension)
        if unit is None:
            return Quantity(None, raw, written, "unknown", dimension)
        value = convert(raw, written, canonical, dimension=dimension)
        status = "ok" if unit.canonical == canonical else "converted"
        return Quantity(value, raw, written, status, dimension)

    for hint in hints:
        declared, unit = unit_from_label(hint, dimension=dimension)
        if not declared:
            continue
        if unit is None:
            return Quantity(None, raw, declared, "unknown", dimension)
        value = convert(raw, declared, canonical, dimension=dimension)
        status = "ok" if unit.canonical == canonical else "converted"
        return Quantity(value, raw, declared, status, dimension)

    return Quantity(float(raw), raw, "", "assumed", dimension)


def convert(value: float, from_unit: str, to_unit: str,
            *, dimension: str | None = None) -> Optional[float]:
    """Convert ``value`` between two written units, or ``None`` if it cannot.

    ``None`` means "do not use this number against that limit" - either
    unit was unreadable, or they measure different things. It never means
    zero and must never be treated as a pass.
    """
    source = parse_unit(from_unit, dimension=dimension)
    target = parse_unit(to_unit, dimension=dimension)
    if not comparable(source, target):
        return None
    base = float(value) * source.factor + source.offset
    return (base - target.offset) / target.factor
