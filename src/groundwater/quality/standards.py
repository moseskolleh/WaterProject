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
        )
        table[normalise_parameter(entry.parameter)] = entry
    return table
