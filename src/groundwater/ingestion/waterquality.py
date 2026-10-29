"""Parser for water quality laboratory result sheets."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import DataFlag, WaterQualityResult, WaterQualitySample
from ..units import _normalise as normalise_unit_text
from ..units import AMBIGUOUS_UNITS, convert, parse_unit, unit_from_label
from ..utils import clean_text, parse_number
from . import common


def _find_results_header(grid: list[list]) -> tuple[int, dict, str] | None:
    """The results table's header row, its columns, and the unit it declares.

    A unit in the result column's header ("Result (ug/L)") is the unit of
    every row whose own unit cell is blank. It was dropped, so arsenic 5
    under "Result (ug/L)" was read as 5 mg/L, five hundred times the
    guideline. Only a unit the toolkit can read is taken: "Result (lab)"
    declares nothing. A row the header's unit cannot measure (E. coli
    under "Result (mg/L)") is then refused rather than read in its
    guideline's unit; that is a choice (QUESTIONS.md item 24).
    """
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
            written, unit = unit_from_label(clean_text(row[cols["value"]]), dimension=None)
            return r, cols, written if unit is not None else ""
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

#: A number as a laboratory writes one: "50", "0,05", "1,250.5", "1.234,5",
#: "5.0E-02". The exponent is part of it: read as far as the "E", "5.0E-02
#: mg/L" was 5.0 followed by a unit nobody could read, so the unit was
#: dropped and arsenic at five times its guideline was read in the row's
#: ug/L and graded Safe. Groups of three are a thousands separator, as
#: parse_number reads them, so "1,250.5 mg/L" is not 1,250 and ".5 mg/L".
_NUMBER = (r"(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?|[.,]\d+)"
           r"(?:e[+-]?\d+)?")

#: A number and the unit written after it: "50", "50 mg/L", "0,05mg/l".
_NUMBER_AND_UNIT = re.compile(
    rf"^(?P<number>{_NUMBER})\s*(?P<unit>[^\d\s()\[\]].*)?$"
)

#: A measured value and whatever is written after it.
_MEASURED = re.compile(rf"{_NUMBER}\s*(?P<rest>.*)$")

#: The families a laboratory's result is written in. A unit of another
#: family after a number is a laboratory's qualifier letter ("0.003 D", "0.2
#: H": a day and an hour to the unit reader), and so is any single letter
#: ("0.1 C", "0.5 F"): read as units, they made the result unreadable.
_QUALITY_DIMENSIONS = ("concentration", "conductivity", "turbidity", "microbial",
                       "ph", "temperature")

#: The most words a unit is written in ("cfu per 100 ml" is four): the
#: runs of a cell's words tried as a unit, so a long note is not tried in
#: every combination of its words.
_UNIT_WORDS = 6

#: A reference temperature after a unit: "450 uS/cm at 25 C", "@ 20 oC".
#: The word boundaries here and below are ASCII ones, as the browser's are.
_REFERENCE_TEMPERATURE = re.compile(
    r"\s*(?:@|\bat)\s*\d+(?:[.,]\d+)?(?:\s*(?:°|º|o|deg\.?)?\s*[cf])?$", re.ASCII)

#: A basis named after a number without "as": nitrogen ("10 N", "10
#: (NO3-N)", "10 mg N/L") or calcium carbonate ("25 (CaCO3)").
_BASIS_NAMED = re.compile(
    r"\bcaco3\b"
    r"|\b(?:(?:no3|no2|nh4|nh3)\s*[-–—−]{0,2}\s*)?(?:n|nitrogen)\b", re.ASCII)


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


def _quality_unit(text: str, dimension: str | None = None) -> bool:
    """Whether ``text`` is a unit a laboratory's result is written in.

    A unit of another family is a laboratory's qualifier letter ("0.003 D",
    "0.2 H": a day and an hour to the unit reader), and so is a lone letter
    ("0.1 C", "0.5 F"), unless the row's own unit (``dimension``) is in the
    letter's family: "68 F" in a row of degrees Celsius is 20 deg C.
    """
    unit = parse_unit(text)
    if unit is None:
        return False
    return unit.dimension == dimension or (
        unit.dimension in _QUALITY_DIMENSIONS and len(re.sub(r"\s+", "", text)) > 1)


def _unit_like(text: str, dimension: str | None = None) -> bool:
    """Whether ``text`` is written as a unit: one a result is written in, one
    refused by name ("ppt"), or a ratio the toolkit does not know ("meq/L")."""
    return (_quality_unit(text, dimension) or "/" in text
            or normalise_unit_text(text) in AMBIGUOUS_UNITS)


def _measured_unit(rest: str, dimension: str | None = None) -> str | None:
    """The unit written after a measured value: ``""`` for none, ``None`` to refuse.

    A unit the toolkit reads is taken ("0.05 mg/L", "8 ug/L*", "0.05 (mg/L)",
    "10 mg/L (as N)", "450 uS/cm at 25 C"); a note holding no unit leaves the
    reading as it was ("0.5 ND", "8 (field)", "0.003 D", a laboratory's
    qualifier letter). Anything else refuses the cell: a unit with more
    written beside it ("0.05 mg/L As", "25 mg/L CaCO3", "0.05 mg/L, est"), a
    basis written without "as" ("10 NO3-N", "10 (N)"), a unit the toolkit
    does not read ("5 meq/L", "5 ppt"), or a note that holds one ("0.05 (DL
    0.01 mg/L)"). Dropped as notes, they read arsenic in mg/L as ug/L and
    nitrate as N as the ion. "As" after a unit is arsenic's symbol on one
    row and the start of a basis on another, and a symbol can be a basis
    that changes the number ("mg/L N"), so refusing rather than reading the
    unit and dropping the symbol is a choice (QUESTIONS.md item 24).
    """
    notes: list[str] = []

    def unwrap(match: re.Match) -> str:
        # a bracket that is a unit or states a basis is read; one that is
        # anything else is a note
        inside = match.group(1).strip()
        if (_quality_unit(inside, dimension) or re.match(r"as\s", inside)
                or _BASIS_NAMED.search(inside)):
            return f" {inside} "
        notes.append(inside)
        return " "

    text = re.sub(r"[(\[]([^()\[\]]*)[)\]]", unwrap, rest.lstrip("."))
    # a stray bracket ("(0.05 mg/L)"), an asterisk and a comma are not part
    # of a unit
    text = re.sub(r"[()\[\]*,;:]", " ", text)
    text = re.sub(r"\s+", " ", _REFERENCE_TEMPERATURE.sub("", text.strip())).strip()
    if text and _quality_unit(text, dimension):
        return text
    tokens = text.split(" ") if text else []
    spans = (" ".join(tokens[i:j]) for i in range(len(tokens))
             for j in range(i + 1, min(i + _UNIT_WORDS, len(tokens)) + 1))
    if ("as" in tokens or _BASIS_NAMED.search(text)
            or any(_unit_like(span, dimension) for span in spans)
            or any(_unit_like(word, dimension) for note in notes for word in note.split())):
        return None
    return ""


def _read_cell(raw_value, dimension: str | None = None) -> dict:
    """What a laboratory's result cell says, in a row whose unit is of
    ``dimension`` (``None`` where the row states none).

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
    # A unit written after a measured value is read as it is after a bound:
    # "0.05 mg/L" in a ug/L row was read as 0.05 ug/L, a two-hundredth of
    # the arsenic guideline, for water at five times it. A note beside the
    # number ("0.5 ND", "8 (field)", "8*") leaves the reading as it was, and
    # a unit that cannot be read as written refuses the cell (_measured_unit).
    unit = ""
    written = _MEASURED.search(plain)
    if written is not None:
        unit = _measured_unit(written.group("rest"), dimension)
        if unit is None:
            return unreadable
    return {"kind": "number", "number": number, "unit": unit, "inclusive": False}


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

    A chemical basis stated on one side only is not a contradiction, as
    :func:`~groundwater.units.comparable` has it: "46 mg/L" in a column of
    "mg/L as CaCO3" is the column's scale, and "10 mg/L as N" in a column of
    "mg/L" keeps the basis the cell names, which the assessment converts.
    """
    if not cell_unit:
        return number, row_unit
    if not normalise_unit_text(row_unit):
        return number, cell_unit
    if normalise_unit_text(cell_unit) == normalise_unit_text(row_unit):
        return number, row_unit
    source, target = parse_unit(cell_unit), parse_unit(row_unit)
    if (source is None or target is None or source.dimension != target.dimension
            or (source.basis and target.basis and source.basis != target.basis)):
        return None, row_unit
    if source.basis and not target.basis:
        return number, cell_unit
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
    header_row, cols, header_unit = located

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
        if header_unit and not normalise_unit_text(unit):
            unit = header_unit
        dl = parse_number(cell("dl"))
        declared = parse_unit(unit)
        read = _read_cell(raw_value, declared.dimension if declared is not None else None)
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
