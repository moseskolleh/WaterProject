"""Parser for VES field data sheets (Excel and CSV).

Reads the Rokel style layout: a header block (client, community,
district, sounding number, GPS east/north, elevation, date, field
supervisor) followed by a table with columns No., AB/2 (m), MN (m) and
apparent resistivity (ohm-m). Values stored as text with leading
zeros (for example ``078.7`` or GPS ``0708958``) parse cleanly.

Duplicate AB/2 values with different MN mark Schlumberger segment
changes; both readings are kept.

Both of the arrays the toolkit models are read. Which one a sheet was
run with is worked out from the sheet itself - the array field in the
header block, the wording above the table, a spacing column headed
"a", and whether there is an MN column at all - and a Wenner sounding
is stored the way ``array_type == "wenner"`` means everywhere else:
``ab2`` holds the Wenner spacing a. Where the sheet settles none of
that the Schlumberger default stands and a flag says it was assumed.
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

# The array a sheet names, wherever on the sheet it names it: the title of a
# template ("SCHLUMBERGER ARRAY VES FIELD DATA"), the array field itself, or
# a note. "Wenner alpha" and "half-Schlumberger" are the same two arrays.
_WENNER_RE = re.compile(r"wenner")
_SCHLUMBERGER_RE = re.compile(r"schlum")

# "a" is the whole name of the Wenner spacing, so the column header is short
# and the reader has to accept the few ways a crew writes it out.
_WENNER_A_HEADERS = frozenset({
    "a", "a (m)", "a(m)", "a m", "a, m", "a (metres)", "a (meters)",
    "a-spacing", "a-spacing (m)", "a spacing", "a spacing (m)",
    "spacing a", "spacing a (m)", "wenner a", "wenner a (m)", "a (wenner)",
})

# A Wenner array is A M N B at equal spacing a, so AB = 3a and a Wenner sheet
# that tabulates AB/2 has written 1.5 a in that column.
_WENNER_AB2_PER_A = 1.5


def _array_named_in(text: str) -> str | None:
    """The array a piece of sheet text names, or ``None``.

    ``None`` covers both the text that names no array and the text that
    names two: an unfilled "Schlumberger / Wenner" template choice settles
    nothing, and reading it as either would be a guess.
    """
    lowered = text.lower()
    wenner = bool(_WENNER_RE.search(lowered))
    schlumberger = bool(_SCHLUMBERGER_RE.search(lowered))
    if wenner == schlumberger:
        return None
    return "wenner" if wenner else "schlumberger"


def _array_named_above_table(grid: list[list], header_row: int) -> str | None:
    """The array the wording above the data table names, if only one is named."""
    found: set[str] = set()
    for row in grid[:header_row]:
        for text in common.row_text(row):
            if _WENNER_RE.search(text):
                found.add("wenner")
            if _SCHLUMBERGER_RE.search(text):
                found.add("schlumberger")
    return next(iter(found)) if len(found) == 1 else None


def _detect_array(
    grid: list[list], header_row: int, cols: dict, fields: dict
) -> tuple[str, list[DataFlag]]:
    """The array a sheet was run with, and the flags reading it raised.

    The forward model, the inversion, the splice and the curve plot all
    branch on ``array_type``, but the reader never looked at the sheet for
    it beyond copying out the array field: a Wenner sounding had no
    ingestion path, and a Wenner sheet headed AB/2 was inverted with AB/2
    for the spacing a (ROADMAP data-ingestion-11). That is wrong by tens of
    percent and nothing downstream can notice.

    The sheet is asked in the order its answers are worth trusting: the
    array field of the header block, then any other wording above the table
    (a template title is boilerplate, so it only speaks when the field is
    silent), then the table's own columns - a spacing column headed "a" is
    the Wenner spacing, and an MN column is the Schlumberger one. Where the
    sheet settles nothing, or contradicts itself, the Schlumberger default
    stands and a flag says what was assumed and why, because an assumption
    made in silence is how the wrong array reaches a client report.
    """
    flags: list[DataFlag] = []
    declared_text = clean_text(fields.get("array_type", ""))
    declared = _array_named_in(declared_text)
    named = declared if declared is not None else _array_named_above_table(grid, header_row)
    from_columns = (
        "wenner" if "a" in cols
        else "schlumberger" if ("mn" in cols or "mn_half" in cols)
        else None
    )

    conflicted = named == "schlumberger" and from_columns == "wenner"
    array_type = "schlumberger" if conflicted else (named or from_columns or "schlumberger")

    if conflicted:
        flags.append(DataFlag(
            "warning", "array_type_conflict",
            "The sheet names the Schlumberger array but heads its spacing "
            "column \"a\", which is the Wenner spacing; the two readings of "
            "the same column differ by half again. The sounding was read as "
            "Schlumberger, with that column taken as AB/2. Confirm the array "
            "with the field crew before the model is used.",
        ))
    elif declared_text and declared is None:
        flags.append(DataFlag(
            "warning", "array_type_unrecognised",
            f"The sheet's array field reads \"{declared_text}\", which does "
            "not name one of the two arrays this toolkit models "
            "(Schlumberger and Wenner); the sounding was read as "
            f"{array_type.capitalize()}. Confirm the array with the field "
            "crew: the wrong forward model is wrong by tens of percent.",
        ))
    elif named is None and from_columns is None:
        flags.append(DataFlag(
            "warning", "array_type_assumed",
            "The sheet does not say which electrode array was used, and its "
            "columns do not settle it either: there is no MN column, which a "
            "Schlumberger sheet carries, and no \"a\" column, which a Wenner "
            "sheet carries. Schlumberger was assumed, as the toolkit's "
            "default. Confirm the array with the field crew: a Wenner "
            "sounding inverted as Schlumberger is wrong by tens of percent "
            "and nothing further down the chain can notice.",
        ))
    elif named is None and from_columns == "wenner":
        flags.append(DataFlag(
            "info", "array_type_inferred",
            "No array is named on the sheet; its spacing column is headed "
            "\"a\", which is the Wenner spacing, so the sounding was read as "
            "Wenner.",
        ))
    return array_type, flags


def _find_data_header(grid: list[list]) -> tuple[int, dict] | None:
    """Locate the data table header row and map columns.

    Returns (row_index, {"no": c, "ab2": c, "a": c, "mn": c, "rho": c}).
    """
    for r, row in enumerate(grid):
        texts = common.row_text(row)
        cols: dict[str, int] = {}
        for c, t in enumerate(texts):
            if not t:
                continue
            if "ab/2" in t or t == "ab2" or "ab / 2" in t:
                cols["ab2"] = c
            # The Wenner spacing column, headed "a" or "a (m)", meant nothing
            # to the reader at all, so a Wenner sheet was dropped whole as
            # having no data table (ROADMAP data-ingestion-11)
            elif t in _WENNER_A_HEADERS:
                cols["a"] = c
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
        if ("ab2" in cols or "a" in cols) and ("rho" in cols or "resistance" in cols):
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
            "no data table found: a header row needs an AB/2 column (or the "
            "Wenner spacing column \"a\") and an apparent-resistivity column "
            "(Resistivity, Rho, ohm.m, ρ or Ω)"
        )
    header_row, cols = located

    array_type, flags = _detect_array(grid, header_row, cols, fields)
    is_wenner = array_type.startswith("wenner")

    ab2, mn, rho = [], [], []
    mn_is_half = "mn" not in cols and "mn_half" in cols
    mn_col = cols.get("mn", cols.get("mn_half"))
    from_resistance = "rho" not in cols
    value_col = cols["rho"] if not from_resistance else cols["resistance"]
    k_col = cols.get("k")
    # The spacing column. A Wenner sheet with its own "a" column is read from
    # it as it stands; anything else is read from AB/2, which on a Wenner
    # sheet is 1.5 a and has to be converted below.
    if is_wenner and "a" in cols:
        spacing_col, wenner_from_ab2 = cols["a"], False
    elif "ab2" in cols:
        spacing_col, wenner_from_ab2 = cols["ab2"], is_wenner
    else:
        spacing_col, wenner_from_ab2 = cols["a"], False
    blank_run = 0
    for row in grid[header_row + 1 :]:
        a = parse_number(row[spacing_col]) if spacing_col < len(row) else None
        r = parse_number(row[value_col]) if value_col < len(row) else None
        m = (
            parse_number(row[mn_col])
            if mn_col is not None and mn_col < len(row)
            else None
        )
        if a is not None and wenner_from_ab2:
            # The sheet is Wenner but tabulates AB/2, and AB = 3a, so the
            # column holds 1.5 a. Taken for the spacing a, as it used to be
            # (ROADMAP data-ingestion-11), every reading sits at half again
            # its true spacing and the whole curve shifts along the depth
            # axis. Convert once, here, so ab2 means what the forward model,
            # the inversion and the plots take it to mean for a Wenner
            # sounding: the spacing a.
            a = a / _WENNER_AB2_PER_A
        if from_resistance and a is not None and r is not None:
            # rho_a = K * (dV/I): use the sheet's own K column when it has
            # one, otherwise the geometric factor of the array the sheet was
            # run with. The Wenner factor is 2 pi a and needs no MN, which is
            # as well: a Wenner sheet does not carry an MN column, so the
            # Schlumberger factor left K unknown and the row was dropped.
            k = parse_number(row[k_col]) if k_col is not None and k_col < len(row) else None
            if k is None and is_wenner:
                k = float(geometric_factor("wenner", a=a))
            elif k is None:
                spacing = 2.0 * m if (m is not None and mn_is_half) else m
                if spacing:
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
    if wenner_from_ab2:
        flags.append(DataFlag(
            "info", "wenner_spacing_from_ab2",
            "The sheet is a Wenner sounding tabulated as AB/2. The Wenner "
            "array has AB = 3a, so each spacing was read as a = two thirds of "
            "the tabulated AB/2, which is the spacing the Wenner geometric "
            "factor and forward model take.",
        ))
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
        array_type=array_type,
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
        discrepant = _overlap_discrepancies(sounding.ab2, sounding.rho_app)
        if discrepant:
            flags.append(
                DataFlag(
                    "warning",
                    "segment_overlap_discrepancy",
                    "At an MN change the two readings at one AB/2 should agree "
                    "within a few percent; these differ by more than "
                    f"{(OVERLAP_DISCREPANCY_RATIO - 1) * 100:.0f} percent: "
                    + "; ".join(discrepant)
                    + ". That is a field problem (potential-electrode contact, "
                    "lateral inhomogeneity at the new MN) or a transcription "
                    "slip, and the inversion merges the pair by geometric "
                    "mean, so part of the model misfit is made by the splice. "
                    "Check the sheet before relying on the deep branch.",
                    sounding.sounding_id,
                )
            )
    sounding.flags = flags
    return sounding, ""


# Readings at one AB/2 taken with two MN spacings should agree closely; a
# ratio beyond this is not the segment shift the splice is built for.
OVERLAP_DISCREPANCY_RATIO = 1.2


def _overlap_discrepancies(ab2: np.ndarray, rho: np.ndarray) -> list[str]:
    """Overlap pairs whose readings disagree by more than the ratio, as
    "AB/2 40 m: 156.1 and 78.7 ohm-m (ratio 1.98)"."""
    out: list[str] = []
    for value in np.unique(ab2):
        readings = rho[(ab2 == value) & np.isfinite(rho) & (rho > 0)]
        if len(readings) < 2:
            continue
        ratio = float(np.max(readings) / np.min(readings))
        if ratio > OVERLAP_DISCREPANCY_RATIO:
            pair = " and ".join(f"{r:g}" for r in readings[:2])
            out.append(f"AB/2 {value:g} m: {pair} ohm-m (ratio {ratio:.2f})")
    return out


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
