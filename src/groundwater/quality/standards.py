"""Guideline and standard values for drinking water parameters.

The bundled table (``data/who_guidelines.csv``) carries WHO Guidelines
for Drinking-water Quality values (4th edition with addenda) split
into health based and acceptability values, plus a Sierra Leone
standard column. Where a confirmed national value is not to hand the
national column mirrors the WHO/regional figure; confirm the values
against the current Sierra Leone Standards Bureau specification and
edit the CSV (or pass a custom file) - no code change is needed.

Range values such as pH are written ``6.5-8.5`` and evaluated as an
allowed interval.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Optional

from ..units import _normalise as normalise_unit_text
from ..units import comparable, convert, parse_unit

_RANGE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$")


@dataclass
class Limit:
    """A guideline limit: either a maximum or an allowed range."""

    maximum: Optional[float] = None
    minimum: Optional[float] = None

    @classmethod
    def parse(cls, text: str) -> Optional["Limit"]:
        text = (text or "").strip()
        if not text:
            return None
        match = _RANGE_RE.match(text)
        if match:
            return cls(minimum=float(match.group(1)), maximum=float(match.group(2)))
        try:
            return cls(maximum=float(text))
        except ValueError:
            return None

    def exceeded_by(self, value: float) -> bool:
        if self.minimum is not None and value < self.minimum:
            return True
        if self.maximum is not None and value > self.maximum:
            return True
        return False

    def __str__(self) -> str:
        if self.minimum is not None:
            return f"{self.minimum:g}-{self.maximum:g}"
        if self.maximum is not None:
            return f"{self.maximum:g}"
        return ""


@dataclass
class StandardEntry:
    parameter: str
    unit: str
    who_health: Optional[Limit]
    who_aesthetic: Optional[Limit]
    sl_standard: Optional[Limit]
    category: str
    note: str
    #: Where the national value came from. ``"provisional"`` means it has not
    #: been checked against the Sierra Leone Standards Bureau specification -
    #: it is a WHO figure carried across, or one adopted from regional
    #: practice. Set it to the issuing specification once confirmed.
    sl_source: str = ""

    @property
    def sl_provisional(self) -> bool:
        """Whether the national value is unconfirmed against the SLSB spec."""
        return self.sl_standard is not None and self.sl_source == "provisional"


#: Said wherever a national verdict is shown, while any national value is
#: still provisional. A compliance failure against an unconfirmed limit is a
#: prompt to check the specification, not a finding to put in front of a
#: regulator.
PROVISIONAL_NATIONAL_NOTE = (
    "The national column in the standards table is provisional: its values "
    "are WHO guideline figures carried across, or limits adopted from "
    "regional practice, and have not been confirmed against the Sierra Leone "
    "Standards Bureau drinking water specification. Confirm the figures "
    "before treating a national exceedance as a compliance finding."
)


def provisional_national_parameters(
    table: dict[str, "StandardEntry"] | None = None,
) -> list[str]:
    """Parameters whose national limit is still unconfirmed."""
    entries = (table or load_standards()).values()
    return sorted(e.parameter for e in entries if e.sl_provisional)


_ALIASES = {
    "ec": "electrical conductivity",
    "conductivity": "electrical conductivity",
    "total dissolved solids": "tds",
    "hardness": "total hardness",
    "nitrate": "nitrate (as no3)",
    "no3": "nitrate (as no3)",
    "nitrite": "nitrite (as no2)",
    "no2": "nitrite (as no2)",
    "ammonia": "ammonia (as n)",
    "ammonium": "ammonia (as n)",
    "nh3": "ammonia (as n)",
    "nh4": "ammonia (as n)",
    "chromium": "chromium (total)",
    "cr": "chromium (total)",
    "faecal coliforms": "e. coli",
    "fecal coliforms": "e. coli",
    "e.coli": "e. coli",
    "escherichia coli": "e. coli",
    "coliforms": "total coliforms",
    "sulphate": "sulfate",
    "so4": "sulfate",
    "aluminum": "aluminium",
}


def normalise_parameter(name: str) -> str:
    key = re.sub(r"\s+", " ", name.strip().lower())
    return _ALIASES.get(key, key)


_PARAMETER_BASIS_RE = re.compile(r"\(\s*as\s+([^)]+?)\s*\)")


def _parameter_basis(parameter: str) -> str:
    """The chemical basis a parameter name states: "Nitrate (as NO3)" -> "no3"."""
    match = _PARAMETER_BASIS_RE.search(str(parameter or ""))
    return match.group(1).lower().replace(" ", "") if match else ""


def to_standard_unit(
    value: float, reported_unit: str, entry: StandardEntry
) -> tuple[Optional[float], str]:
    """Put a reported value on the scale the standards table uses.

    Returns ``(converted, reason)``. ``converted`` is ``None`` when the value
    must not be used against this parameter's limits - an unreadable unit, or
    one that measures something else. That is never the same as zero, and a
    caller must drop the value rather than fall back to the raw number.

    ``reason`` is ``""`` on a clean conversion, ``"unit_assumed"`` when the
    laboratory reported no usable unit and the guideline's own was assumed,
    ``"unit_basis_assumed"`` when one side names a chemical basis the other
    does not, or an ``INDETERMINATE_REASONS`` code on refusal.
    """
    reported = str(reported_unit or "").strip()
    guideline = str(entry.unit or "").strip()

    if not reported:
        # No unit on the sheet. The guideline's own unit is the only reading
        # under which the number means anything; the assumption is recorded
        # rather than hidden.
        return float(value), "unit_assumed"
    if not guideline:
        # The standards table itself names no unit, so there is no scale to
        # convert onto and nothing to disagree about.
        return float(value), ""
    if normalise_unit_text(reported) == normalise_unit_text(guideline):
        # Written the same way: same scale, whether or not the unit module has
        # ever heard of the unit. Keeps a newly added guideline unit from
        # making every sample indeterminate.
        return float(value), ""

    source = parse_unit(reported)
    target = parse_unit(guideline)

    if target is not None and target.dimension == "ph":
        # pH is the one absolute scale here with no rival: there is no such
        # thing as pH in another unit, so a sheet carrying "mg/L" beside a pH
        # of 7.2 is a template artefact, not a different measurement.
        if source is None or source.dimension != "ph":
            return float(value), "unit_assumed"
        return float(value), ""

    if source is None or target is None:
        return None, "unit_unreadable"
    if not comparable(source, target):
        return None, "unit_mismatch"
    converted = convert(value, reported, guideline)
    if converted is None:  # pragma: no cover - comparable() already checked
        return None, "unit_mismatch"
    if source.basis and not target.basis:
        # The unit names a chemical reference the guideline's unit does not.
        # The parameter name often carries it instead, so look there before
        # deciding: "Nitrate (as NO3)" reported in "mg/L as N" is a different
        # number by a factor of 4.4, and grading it at face value passed a
        # sample at 44 mg/L as NO3 that the guideline puts over its limit.
        named = _parameter_basis(entry.parameter)
        if named and named != source.basis:
            return None, "unit_basis_conflict"
        if not named:
            # Nothing states the guideline's basis, so the reading is taken
            # but it is worth an analyst's eye: calcium as Ca and calcium as
            # CaCO3 differ by a factor of 2.5.
            return converted, "unit_basis_assumed"
    elif target.basis and not source.basis:
        return converted, "unit_basis_assumed"
    return converted, ""


def canonical_values(
    sample, table: dict[str, StandardEntry] | None = None
) -> dict[str, float]:
    """Every measured result in the sample, on the standards table's scale.

    Keyed by normalised parameter name. A result whose unit cannot be
    reconciled with its guideline is *left out* rather than passed through
    raw: the aggregate indices built on these numbers - the water quality
    index, the hazard index, the ionic balance, the corrosivity indices -
    all assume mg/L, and a sample reported in ug/L quietly produced a hazard
    index a thousand times too high and an "unsuitable for drinking" rating
    for clean water.
    """
    table = table if table is not None else load_standards()
    values: dict[str, float] = {}
    for result in getattr(sample, "results", []):
        if result.value is None:
            continue
        key = normalise_parameter(result.parameter)
        entry = table.get(key)
        if entry is None:
            # No guideline entry, so no declared scale to convert onto. The
            # value is carried as written; nothing downstream has a limit for
            # it either.
            values[key] = float(result.value)
            continue
        converted, _ = to_standard_unit(float(result.value), result.unit, entry)
        if converted is not None:
            values[key] = converted
    return values


def load_standards(path: str | Path | None = None) -> dict[str, StandardEntry]:
    """Load the standards table keyed by normalised parameter name."""
    if path is None:
        source = resources.files("groundwater.data").joinpath("who_guidelines.csv")
        fh = source.open("r", encoding="utf-8")
    else:
        fh = open(path, "r", encoding="utf-8")
    with fh:
        rows = list(csv.DictReader(fh))
    table: dict[str, StandardEntry] = {}
    for row in rows:
        entry = StandardEntry(
            parameter=row["parameter"],
            unit=row["unit"],
            who_health=Limit.parse(row.get("who_health_gv", "")),
            who_aesthetic=Limit.parse(row.get("who_aesthetic", "")),
            sl_standard=Limit.parse(row.get("sl_standard", "")),
            category=row.get("category", ""),
            note=row.get("note", ""),
            sl_source=(row.get("sl_source") or "").strip(),
        )
        table[normalise_parameter(entry.parameter)] = entry
    return table
