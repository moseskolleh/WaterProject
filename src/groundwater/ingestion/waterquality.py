"""Parser for water quality laboratory result sheets."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import DataFlag, WaterQualityResult, WaterQualitySample
from ..units import _normalise as normalise_unit_text
from ..units import convert, parse_unit
from ..utils import clean_text, parse_number
from . import common


def _find_results_header(grid: list[list]) -> tuple[int, dict] | None:
    for r, row in enumerate(grid):
        texts = common.row_text(row)
        cols: dict[str, int] = {}
        for c, t in enumerate(texts):
            if not t:
                continue
            if t.startswith("parameter") or t.startswith("determinand"):
                cols["parameter"] = c
            elif t.startswith("unit"):
                cols["unit"] = c
            elif t.startswith("value") or t.startswith("result"):
                cols["value"] = c
            elif "detection" in t or t == "dl":
                cols["dl"] = c
            elif t.startswith("method"):
                cols["method"] = c
        if "parameter" in cols and "value" in cols:
            return r, cols
    return None


#: What a laboratory writes for "nothing found": read as a below-detection
#: result with no stated limit, which the assessment then judges by the
#: parameter (a microbiological count with nothing in 100 mL meets its
#: guideline; a chemical determinand still needs the method's limit). The
#: same words often carry that limit after them ("ND (<0.05)", "BDL (0.02)",
#: "ND at 0.05"); only an exact match once counted, and every one of those
#: was graded as a measured concentration exceeding a health guideline.
ABSENCE_TOKENS = frozenset({
    "absent", "nd", "n.d", "n/d", "nil", "none", "not detected", "none detected",
    "bdl", "below detection", "below detection limit", "<dl", "negative", "neg",
})

#: What a laboratory writes when it saw the determinand and put no number to
#: it. For a determinand whose limit is zero that is the whole finding: a
#: sample with E. coli 0 and total coliforms TNTC was graded "Safe" because
#: the count read as "not measured".
PRESENCE_TOKENS = frozenset({
    "tntc", "t.n.t.c", "too numerous to count", "confluent", "confluent growth",
    "present", "positive", "pos", "+ve", "detected",
})

#: Words that introduce a lower bound, and whether the bound itself is a
#: possible value. ">=50" is at least 50; ">50" is more than 50.
_LOWER_BOUND_WORDS = (
    (">=", True), ("=>", True), (">", False), ("at least", True),
    ("more than", False), ("greater than", False), ("above", False),
    ("over", False),
)

#: Words that introduce an upper bound: "<0.05" is below a detection limit
#: of 0.05.
_UPPER_BOUND_WORDS = ("<=", "=<", "<", "less than")

#: What may stand between an absence word and the limit it carries:
#: "ND (DL 0.05)", "ND (DL=0.05)", "ND at 0.05", "ND (LOD 0.05)".
_LIMIT_WORD = re.compile(
    r"^(?:at|dl|d\.l\.?|lod|loq|mdl|detection limit|limit of detection|limit)"
    r"\s*[=:]?\s*"
)

#: A bound with no number: "<DL", "< LOQ".
_LIMIT_ONLY = re.compile(r"^(?:dl|d\.l\.?|lod|loq|mdl|detection limit|detection)$")

#: "Absent/100 mL", "Present in 100 mL": the volume examined, not a limit.
_VOLUME = re.compile(r"^(?:/|per|in)\s*100\s*ml$")

#: A number and the unit written after it: "50", "50 mg/L", "0,05mg/l".
_NUMBER_AND_UNIT = re.compile(
    r"^(?P<number>\d+(?:[.,]\d+)?|[.,]\d+)\s*(?P<unit>[^\d\s()\[\]].*)?$"
)


def _leading_word(text: str, words) -> str | None:
    """The longest of ``words`` that ``text`` starts with, as a whole word."""
    for word in sorted(words, key=len, reverse=True):
        if text.startswith(word):
            rest = text[len(word):]
            if not rest or not rest[0].isalpha():
                return word
    return None


def _number_and_unit(text: str) -> tuple[float, str] | None:
    """``(number, unit)`` from "0.05 mg/L" or "(<0.05)", or None."""
    text = text.strip().strip("()[]").strip()
    match = _NUMBER_AND_UNIT.match(text)
    if not match:
        return None
    unit = (match.group("unit") or "").strip().rstrip(".").strip()
    return parse_number(match.group("number")), unit


def _read_cell(raw_value) -> dict:
    """What a laboratory's result cell says.

    ``kind`` is one of ``number``, ``below`` (a non-detect, with the limit
    it states if any), ``above`` (a lower bound: ">50", "TNTC"), ``empty``,
    ``text`` (words that are not a result, such as "Not analysed"), or
    ``unreadable``: a cell that starts like a qualified result and could not
    be read. That last one used to fall through to a plain number parse,
    which read "ND (DL 0.05)" as a measured 0.05, ">50 mg/L" as exactly 50
    and "Absent/100 mL" as a count of 100.
    """
    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        number = parse_number(raw_value)
        return {"kind": "number" if number is not None else "empty",
                "number": number, "unit": "", "inclusive": False}
    text = clean_text(raw_value)
    if not text:
        return {"kind": "empty", "number": None, "unit": "", "inclusive": False}
    plain = (text.lower().replace("\u2265", ">=").replace("\u2264", "<=")
             .rstrip(".").strip())
    unreadable = {"kind": "unreadable", "number": None, "unit": "",
                  "inclusive": False}

    def below(rest: str) -> dict:
        # what follows an absence word or a "<": nothing, the volume
        # examined, or a limit with an optional unit
        rest = rest.strip().lstrip(",;:.-").strip()
        rest = rest.strip("()[]").strip()
        if not rest or _VOLUME.match(rest) or _LIMIT_ONLY.match(rest):
            return {"kind": "below", "number": None, "unit": "",
                    "inclusive": False}
        rest = _LIMIT_WORD.sub("", rest)
        rest = re.sub(r"^(?:<=|=<|<)\s*", "", rest)
        read = _number_and_unit(rest)
        if read is None:
            return unreadable
        return {"kind": "below", "number": read[0], "unit": read[1],
                "inclusive": False}

    def above(rest: str, inclusive: bool) -> dict:
        rest = rest.strip().strip("()[]").strip()
        plus = re.match(r"^(\d+(?:[.,]\d+)?|[.,]\d+)\s*\+\s*(.*)$", rest)
        if plus:
            rest, inclusive = plus.group(1) + " " + plus.group(2), True
        read = _number_and_unit(rest)
        if read is None:
            return unreadable
        return {"kind": "above", "number": read[0], "unit": read[1],
                "inclusive": inclusive}

    word = _leading_word(plain, ABSENCE_TOKENS)
    if word is not None:
        return below(plain[len(word):])
    word = _leading_word(plain, PRESENCE_TOKENS)
    if word is not None:
        rest = plain[len(word):].strip().lstrip(",;:-").strip()
        if not rest or _VOLUME.match(rest):
            return {"kind": "above", "number": 0.0, "unit": "",
                    "inclusive": False}
        # "TNTC (>300)": the count is at least the stated bound
        inner = rest.strip("()[]").strip()
        for prefix, inclusive in _LOWER_BOUND_WORDS:
            if inner.startswith(prefix):
                return above(inner[len(prefix):], inclusive)
        return unreadable
    for prefix in _UPPER_BOUND_WORDS:
        if plain.startswith(prefix):
            return below(plain[len(prefix):])
    for prefix, inclusive in _LOWER_BOUND_WORDS:
        if plain.startswith(prefix):
            return above(plain[len(prefix):], inclusive)
    if re.match(r"^(\d+(?:[.,]\d+)?|[.,]\d+)\s*\+", plain):
        # "50+" is 50 or more
        return above(plain, True)
    number = parse_number(raw_value)
    if number is None:
        return {"kind": "text", "number": None, "unit": "", "inclusive": False}
    return {"kind": "number", "number": number, "unit": "", "inclusive": False}


def _as_written(text: str, unit: str) -> str:
    """A unit read from the lower-cased cell, in the case the cell wrote it."""
    at = text.lower().rfind(unit) if unit else -1
    return text[at:at + len(unit)] if at >= 0 else unit


def _in_row_unit(number: float, cell_unit: str, row_unit: str):
    """The number on the row's scale, and the unit to record for the row.

    A unit written in the cell ("ND (<0.05 mg/L)") is read, not dropped: it
    becomes the row's unit when the unit column is blank, and is converted
    onto the column's unit when the two differ. ``(None, row_unit)`` when
    they cannot be reconciled, which is never the same as zero.
    """
    if not cell_unit:
        return number, row_unit
    if not normalise_unit_text(row_unit):
        return number, cell_unit
    if normalise_unit_text(cell_unit) == normalise_unit_text(row_unit):
        return number, row_unit
    source, target = parse_unit(cell_unit), parse_unit(row_unit)
    if (source is None or target is None or source.dimension != target.dimension
            or source.basis != target.basis):
        return None, row_unit
    return convert(number, cell_unit, row_unit), row_unit


def read_quality_workbook(path: str | Path) -> WaterQualitySample:
    grid, _ = common.load_grid(path)
    return quality_from_grid(grid, source=str(path))


def quality_from_grid(grid: list[list], source: str = "") -> WaterQualitySample:
    """Read a laboratory sheet already loaded as a grid of cell values."""
    fields = common.extract_header_fields(grid)
    site = common.site_from_fields(fields, source=source)
    flags: list[DataFlag] = []

    located = _find_results_header(grid)
    if located is None:
        raise ValueError(f"No results table (Parameter/Value) found in {source}")
    header_row, cols = located

    results: list[WaterQualityResult] = []
    for row in grid[header_row + 1 :]:
        def cell(key):
            c = cols.get(key)
            return row[c] if c is not None and c < len(row) else None

        parameter = clean_text(cell("parameter"))
        if not parameter or parameter.lower().startswith("note"):
            continue
        raw_value = cell("value")
        unit = clean_text(cell("unit"))
        dl = parse_number(cell("dl"))
        read = _read_cell(raw_value)
        kind = read["kind"]
        number = read["number"]
        if number is not None:
            cell_unit = _as_written(clean_text(raw_value), read["unit"])
            number, unit = _in_row_unit(number, cell_unit, unit)
            if number is None:
                # the cell names a unit the column contradicts
                kind = "unreadable"
        value = None
        greater_than = None
        below_detection = False
        if kind == "number":
            value = number
        elif kind == "below":
            # "<X" bounds the true concentration above by X, and so does a
            # filled detection-limit column; the larger of the two is the
            # one the laboratory can stand behind. Taking the column alone
            # graded "<0.05" beside a column of 0.001 against 0.001.
            below_detection = True
            stated = [x for x in (number, dl) if x is not None]
            dl = max(stated) if stated else None
        elif kind == "above":
            greater_than = number
        elif kind == "empty":
            # A blank result beside a filled detection-limit column is the
            # one layout where the column is the result. Not analysed, N/A,
            # TNTC, Present and ">50" are not blanks, and reading any of them
            # this way reported a detection as "not detected".
            below_detection = dl is not None
        results.append(
            WaterQualityResult(
                parameter=parameter,
                value=value,
                unit=unit,
                detection_limit=dl,
                below_detection=below_detection,
                method=clean_text(cell("method")),
                greater_than=greater_than,
                greater_than_inclusive=bool(read["inclusive"]),
                unreadable=clean_text(raw_value) if kind == "unreadable" else "",
            )
        )

    sample = WaterQualitySample(
        site=site,
        sample_id=str(fields.get("sample_id", "") or ""),
        borehole_ref=str(fields.get("borehole_ref", "") or ""),
        sample_date=str(fields.get("sample_date", fields.get("date", ""))),
        laboratory=fields.get("laboratory", ""),
        results=results,
        source=source,
    )
    measured = [r for r in results if r.value is not None or r.below_detection]
    if not measured:
        flags.append(
            DataFlag("error", "no_results", "No measured values found in the sheet.")
        )
    sample.flags = flags
    return sample
