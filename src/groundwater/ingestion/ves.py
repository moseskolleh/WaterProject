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
from pathlib import Path

import numpy as np

from ..models import DataFlag, VESSounding
from ..utils import clean_text, parse_number
from . import common


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
            elif t.startswith("mn") and "/2" not in t:
                cols["mn"] = c
            elif t.startswith("mn/2") or "mn / 2" in t:
                cols["mn_half"] = c
            elif "resistivity" in t or t.startswith("rho") or "ohm" in t:
                cols["rho"] = c
            elif t in ("no.", "no", "reading", "n"):
                cols["no"] = c
        if "ab2" in cols and "rho" in cols:
            return r, cols
    return None


def _sounding_from_grid(
    grid: list[list], source: str, sheet_name: str = ""
) -> VESSounding | None:
    fields = common.extract_header_fields(grid)
    site = common.site_from_fields(fields, source=source)
    located = _find_data_header(grid)
    if located is None:
        return None
    header_row, cols = located

    ab2, mn, rho = [], [], []
    flags: list[DataFlag] = []
    mn_is_half = "mn" not in cols and "mn_half" in cols
    mn_col = cols.get("mn", cols.get("mn_half"))
    blank_run = 0
    for row in grid[header_row + 1 :]:
        a = parse_number(row[cols["ab2"]]) if cols["ab2"] < len(row) else None
        r = parse_number(row[cols["rho"]]) if cols["rho"] < len(row) else None
        m = (
            parse_number(row[mn_col])
            if mn_col is not None and mn_col < len(row)
            else None
        )
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
        return None

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
    return sounding


def _duplicate_ab2_count(ab2: np.ndarray) -> int:
    unique, counts = np.unique(ab2, return_counts=True)
    return int(np.sum(counts > 1))


def read_ves_workbook(path: str | Path) -> list[VESSounding]:
    """Read every sounding in a VES workbook (one worksheet per sounding)."""
    path = Path(path)
    soundings = []
    for name in common.sheet_names(path):
        grid, title = common.load_grid(path, sheet=name)
        sounding = _sounding_from_grid(grid, source=str(path), sheet_name=title)
        if sounding is not None:
            soundings.append(sounding)
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
