"""Parser for water quality laboratory result sheets."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import DataFlag, WaterQualityResult, WaterQualitySample
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
#: guideline; a chemical determinand still needs the method's limit).
ABSENCE_TOKENS = frozenset({
    "absent", "nd", "n.d", "n/d", "nil", "none", "not detected", "none detected",
    "bdl", "below detection", "below detection limit", "<dl", "negative", "neg",
})

#: The same words with the laboratory's detection limit written after them:
#: "ND (<0.05)", "BDL (0.02)", "ND<0.1", "Not detected (<0.001)". Only an
#: exact match counted before, so every one of these was read as a measured
#: concentration and graded EXCEEDS HEALTH GUIDELINE - the arsenic a
#: laboratory reported as absent came out as the worst reading on the sheet.
_ABSENCE_WITH_LIMIT = re.compile(
    r"^(?P<word>[a-z][a-z.\s/]*?)\s*[(\[]?\s*<?\s*"
    r"(?P<limit>\d+(?:[.,]\d+)?)\s*[)\]]?\.?$"
)

#: What a laboratory writes when it saw the determinand and put no number to
#: it. For a determinand whose limit is zero that is the whole finding: a
#: sample with E. coli 0 and total coliforms TNTC was graded "Safe" because
#: the count read as "not measured".
PRESENCE_TOKENS = frozenset({
    "tntc", "t.n.t.c", "too numerous to count", "confluent", "confluent growth",
    "present", "positive", "pos", "+ve", "detected",
})

#: "greater than" results: at least this much, not exactly this much.
_GREATER_THAN = re.compile(r"^(?:>|>=|\u2265|more than|greater than)\s*"
                           r"(?P<value>\d+(?:[.,]\d+)?)\s*\+?$")


def _absence_limit(text: str) -> float | None:
    """The detection limit an absence phrase carries, if it carries one."""
    match = _ABSENCE_WITH_LIMIT.match(text.lower().strip())
    if not match:
        return None
    word = re.sub(r"[\s.]+$", "", match.group("word")).strip()
    if word not in ABSENCE_TOKENS:
        return None
    return parse_number(match.group("limit"))


def read_quality_workbook(path: str | Path) -> WaterQualitySample:
    grid, _ = common.load_grid(path)
    fields = common.extract_header_fields(grid)
    site = common.site_from_fields(fields, source=str(path))
    flags: list[DataFlag] = []

    located = _find_results_header(grid)
    if located is None:
        raise ValueError(f"No results table (Parameter/Value) found in {path}")
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
        text_value = clean_text(raw_value)
        plain = text_value.lower().rstrip(".")
        # "<1", the words a certificate uses for the same thing, and those
        # same words with the limit written after them ("ND (<0.05)")
        worded_limit = _absence_limit(text_value)
        below_detection = (
            text_value.startswith("<")
            or plain in ABSENCE_TOKENS
            or worded_limit is not None
        )
        # A count the laboratory saw and did not quantify, and a ">50" that
        # used to be read as exactly 50.
        greater_than = None
        if not below_detection:
            if plain in PRESENCE_TOKENS:
                greater_than = 0.0
            else:
                match = _GREATER_THAN.match(plain)
                if match:
                    greater_than = parse_number(match.group("value"))
        value = (
            None
            if plain in ABSENCE_TOKENS or worded_limit is not None
            or greater_than is not None
            else parse_number(raw_value)
        )
        dl = parse_number(cell("dl"))
        if worded_limit is not None and dl is None:
            dl = worded_limit
        if below_detection:
            # A "<X" marker means the true concentration is unknown, bounded
            # above by X. The measured value must be cleared so downstream
            # assessment treats the row as below-detection and never grades it
            # as a real concentration equal to the limit. Keep an explicit
            # detection-limit column when the lab filled one; otherwise use X.
            dl = dl if dl is not None else value
            value = None
        results.append(
            WaterQualityResult(
                parameter=parameter,
                value=value,
                unit=clean_text(cell("unit")),
                detection_limit=dl,
                below_detection=below_detection or (value is None and dl is not None),
                method=clean_text(cell("method")),
                greater_than=greater_than,
            )
        )

    sample = WaterQualitySample(
        site=site,
        sample_id=str(fields.get("sample_id", "") or ""),
        borehole_ref=str(fields.get("borehole_ref", "") or ""),
        sample_date=str(fields.get("sample_date", fields.get("date", ""))),
        laboratory=fields.get("laboratory", ""),
        results=results,
        source=str(path),
    )
    measured = [r for r in results if r.value is not None or r.below_detection]
    if not measured:
        flags.append(
            DataFlag("error", "no_results", "No measured values found in the sheet.")
        )
    sample.flags = flags
    return sample
