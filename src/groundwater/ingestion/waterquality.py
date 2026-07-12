"""Parser for water quality laboratory result sheets."""

from __future__ import annotations

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
        below_detection = text_value.startswith("<")
        value = parse_number(raw_value)
        dl = parse_number(cell("dl"))
        if below_detection and dl is None:
            dl = value
            value = None
        results.append(
            WaterQualityResult(
                parameter=parameter,
                value=value,
                unit=clean_text(cell("unit")),
                detection_limit=dl,
                below_detection=below_detection or (value is None and dl is not None),
                method=clean_text(cell("method")),
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
