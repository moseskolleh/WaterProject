"""Parser for VES field data sheets (Excel and CSV).

Reads the Rokel style layout: a header block (client, community,
district, sounding number, GPS east/north, elevation, date, field
supervisor) followed by a table with columns No., AB/2 (m), MN (m) and
apparent resistivity (ohm-m). Values stored as text with leading
zeros (for example ``078.7`` or GPS ``0708958``) parse cleanly.

Duplicate AB/2 values with different MN mark Schlumberger segment
changes; both readings are kept.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import numpy as np

from ..ves.arrays import geometric_factor
from ..models import DataFlag, VESSounding
from ..utils import clean_text, parse_number
from . import common

# "MN/2", "MN / 2", "MN /2 (m)" - a typed header keeps its spaces
_MN_HALF_RE = re.compile(r"mn\s*/\s*2")
# "Resistance (ohm)", "R (ohm)", "V/I", "dV/I", "ΔV/I": a measured resistance
_RESISTANCE_RE = re.compile(r"resistance|^r\s*\(|v\s*/\s*i")


def _find_data_header(grid: list[list]) -> tuple[int, dict] | None:
    """Locate the data table header row and map columns.

    Returns (row_index, {"no": c, "ab2": c, "mn": c, "rho": c}).
    """
    for r, row in enumerate(grid):
        texts = common.row_text(row)
        cols: dict[str, int] = {}
        for c, t in enumerate(texts):
            if not t:
                continue
            if "ab/2" in t or t == "ab2" or "ab / 2" in t:
                cols["ab2"] = c
            # half-MN first, and tolerant of the spaces a typed header carries:
            # "MN / 2 (m)" does not contain the literal "/2", so it used to fall
            # through to the full-MN branch and halve every potential spacing
            elif t.startswith("mn") and _MN_HALF_RE.search(t):
                cols["mn_half"] = c
            elif t.startswith("mn"):
                cols["mn"] = c
            # a sheet that records V/I (a resistance, in ohms) is not a
            # resistivity sheet: "R (ohm)" used to match the "ohm" test below
            # and every reading came through as a resistivity of 0.9
            elif _RESISTANCE_RE.search(t):
                cols["resistance"] = c
            elif (
                "resistivity" in t or t.startswith("rho") or "ohm" in t
                or "apparent" in t or "ρ" in t or "ω" in t
            ):
                cols["rho"] = c
            elif t in ("k", "k (m)", "k(m)", "geometric factor"):
                cols["k"] = c
            elif t in ("no.", "no", "reading", "n"):
                cols["no"] = c
        if "ab2" in cols and ("rho" in cols or "resistance" in cols):
            return r, cols
    return None


def _sounding_from_grid(
    grid: list[list], source: str, sheet_name: str = ""
) -> VESSounding | None:
    sounding, _ = _sounding_or_reason(grid, source, sheet_name)
    return sounding


def _sounding_or_reason(
    grid: list[list], source: str, sheet_name: str = ""
) -> tuple[VESSounding | None, str]:
    """The sounding on a sheet, or the reason there is none.

    A sheet the reader could not use was dropped without a word, so a
    three-sheet workbook with one mislabelled sheet came back as two
    soundings and nothing said so.
    """
    fields = common.extract_header_fields(grid)
    site = common.site_from_fields(fields, source=source)
    located = _find_data_header(grid)
    if located is None:
        return None, (
            "no data table found: a header row needs an AB/2 column and an "
            "apparent-resistivity column (Resistivity, Rho, ohm.m, ρ or Ω)"
        )
    header_row, cols = located

    ab2, mn, rho = [], [], []
    flags: list[DataFlag] = []
    mn_is_half = "mn" not in cols and "mn_half" in cols
    mn_col = cols.get("mn", cols.get("mn_half"))
    from_resistance = "rho" not in cols
    value_col = cols["rho"] if not from_resistance else cols["resistance"]
    k_col = cols.get("k")
    blank_run = 0
    for row in grid[header_row + 1 :]:
        a = parse_number(row[cols["ab2"]]) if cols["ab2"] < len(row) else None
        r = parse_number(row[value_col]) if value_col < len(row) else None
        m = (
            parse_number(row[mn_col])
            if mn_col is not None and mn_col < len(row)
            else None
        )
        if from_resistance and a is not None and r is not None:
            # rho_a = K * (dV/I): use the sheet's own K column when it has
            # one, otherwise the Schlumberger factor from the spacings
            k = parse_number(row[k_col]) if k_col is not None and k_col < len(row) else None
            spacing = 2.0 * m if (m is not None and mn_is_half) else m
            if k is None and spacing:
                k = float(geometric_factor("schlumberger", ab2=a, mn=spacing))
            r = k * r if k else None
        if a is None and r is None:
            fully_blank = all(v is None or clean_text(v) == "" for v in row)
            if ab2 and fully_blank:
                # Tolerate an isolated blank spacer row inside the table -
                # field sheets routinely leave one at a Schlumberger MN segment
                # change. Only two consecutive fully-blank rows mark the true
                # end of the table, so the deep branch after a spacer is kept.
                blank_run += 1
                if blank_run >= 2:
                    break
            continue
        if a is None or r is None:
            continue
        blank_run = 0
        if m is not None and mn_is_half:
            m = 2.0 * m
        ab2.append(a)
        mn.append(m if m is not None else np.nan)
        rho.append(r)

    if not ab2:
        return None, (
            "the data table has a header but no numeric rows; if the cells "
            "hold formulas, open the workbook in Excel and save it so the "
            "values are stored"
        )
    if from_resistance:
        flags.append(DataFlag(
            "info", "rho_computed_from_resistance",
            "The sheet records a resistance (V/I), not a resistivity; apparent "
            "resistivity was computed as K x R from the electrode spacings"
            + ("" if k_col is None else " and the sheet's K column") + ".",
        ))

    sounding_id = str(fields.get("sounding_id", "") or sheet_name or "VES 1")
    sounding = VESSounding(
        site=site,
        sounding_id=sounding_id if sounding_id else "VES 1",
        ab2=np.array(ab2),
        mn=np.array(mn),
        rho_app=np.array(rho),
        array_type=str(fields.get("array_type", "schlumberger")).lower() or "schlumberger",
        instrument=fields.get("instrument", ""),
        source=str(source),
    )

    # Data quality checks
    if np.any(sounding.rho_app <= 0):
        flags.append(
            DataFlag(
                "error",
                "nonpositive_resistivity",
                "Apparent resistivity values must be positive.",
                sounding.sounding_id,
            )
        )
    if np.any(np.diff(sounding.ab2) < 0):
        flags.append(
            DataFlag(
                "warning",
                "ab2_not_sorted",
                "AB/2 values are not in increasing order; check the sheet.",
                sounding.sounding_id,
            )
        )
    finite_mn = sounding.mn[np.isfinite(sounding.mn)]
    if len(finite_mn) and np.any(sounding.ab2[np.isfinite(sounding.mn)] <= finite_mn / 2):
        flags.append(
            DataFlag(
                "warning",
                "mn_exceeds_ab",
                "MN/2 is not smaller than AB/2 for some readings.",
                sounding.sounding_id,
            )
        )
    dup = _duplicate_ab2_count(sounding.ab2)
    if dup:
        flags.append(
            DataFlag(
                "info",
                "segment_overlap",
                f"{dup} AB/2 value(s) repeated with different MN (segment changes); "
                "both readings kept.",
                sounding.sounding_id,
            )
        )
    sounding.flags = flags
    return sounding, ""


def _duplicate_ab2_count(ab2: np.ndarray) -> int:
    unique, counts = np.unique(ab2, return_counts=True)
    return int(np.sum(counts > 1))


def read_ves_workbook(
    path: str | Path, skipped: list[DataFlag] | None = None
) -> list[VESSounding]:
    """Read every sounding in a VES workbook (one worksheet per sounding).

    A sheet that yields no sounding is skipped; pass ``skipped`` to be told
    which sheets and why (one warning flag per sheet), so a mislabelled
    sheet in a three-sheet workbook does not vanish silently.
    """
    path = Path(path)
    soundings = []
    for name in common.sheet_names(path):
        grid, title = common.load_grid(path, sheet=name)
        sounding, reason = _sounding_or_reason(grid, source=str(path), sheet_name=title)
        if sounding is not None:
            soundings.append(sounding)
        elif skipped is not None:
            skipped.append(DataFlag(
                "warning", "sheet_skipped",
                f"Sheet '{title}' was skipped: {reason}.",
            ))
    return soundings


def read_ves_csv(path: str | Path) -> VESSounding:
    """Read a single sounding from CSV (same layout as one worksheet)."""
    path = Path(path)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        grid = [row for row in csv.reader(fh)]
    grid = [[cell if cell != "" else None for cell in row] for row in grid]
    sounding = _sounding_from_grid(grid, source=str(path), sheet_name=path.stem)
    if sounding is None:
        raise ValueError(f"No VES data table found in {path}")
    return sounding
