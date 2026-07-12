"""Parser for drilling log sheets (Excel template and WiNGiN style tables)."""

from __future__ import annotations

from pathlib import Path

from ..models import DataFlag, DrillingLog, LithologyInterval
from ..utils import clean_text, parse_depth_interval, parse_number
from . import common


def _find_log_header(grid: list[list]) -> tuple[int, dict] | None:
    """Locate the drilling table header row and map its columns."""
    for r, row in enumerate(grid):
        texts = common.row_text(row)
        cols: dict[str, int] = {}
        for c, t in enumerate(texts):
            if not t:
                continue
            if ("depth" in t and "interval" in t) or t.startswith("depth /"):
                cols["interval"] = c
            elif t.startswith("depth") and "interval" not in cols:
                cols.setdefault("interval", c)
            elif t.startswith("from"):
                cols.setdefault("from_time", c)
            elif t.startswith("to"):
                cols.setdefault("to_time", c)
            elif "penetration" in t:
                cols["rate"] = c
            elif "sample" in t or "litholog" in t or "description" in t:
                cols.setdefault("description", c)
            elif "diameter" in t or "bit" in t:
                cols.setdefault("diameter", c)
            elif "strike" in t:
                cols["strike"] = c
        if "interval" in cols:
            return r, cols
    return None


def read_drilling_workbook(path: str | Path) -> DrillingLog:
    grid, _ = common.load_grid(path)
    return drilling_from_grid(grid, source=str(path))


def drilling_from_grid(grid: list[list], source: str = "") -> DrillingLog:
    fields = common.extract_header_fields(grid, max_rows=len(grid))
    site = common.site_from_fields(fields, source=source)
    flags: list[DataFlag] = []

    located = _find_log_header(grid)
    intervals: list[LithologyInterval] = []
    strikes: list[float] = []
    if located is not None:
        header_row, cols = located
        for row in grid[header_row + 1 :]:
            def cell(key):
                c = cols.get(key)
                return row[c] if c is not None and c < len(row) else None

            raw_interval = cell("interval")
            if clean_text(raw_interval).lower().startswith("note"):
                continue
            interval = parse_depth_interval(raw_interval)
            if interval is None:
                continue
            top, bottom = interval
            description = clean_text(cell("description"))
            intervals.append(
                LithologyInterval(
                    top_m=top,
                    bottom_m=bottom,
                    description=description,
                    from_time=clean_text(cell("from_time")),
                    to_time=clean_text(cell("to_time")),
                    penetration_rate_m_per_min=parse_number(cell("rate")),
                    bit_diameter_in=parse_number(cell("diameter")),
                )
            )
            strike = parse_number(cell("strike"))
            if strike is not None:
                strikes.append(strike)

    # Water strikes noted as text lines ("First water strike: 12m")
    for row in grid:
        for c in row:
            text = clean_text(c).lower()
            if "water strike" in text and not text.startswith("note"):
                value = parse_number(text.split(":")[-1])
                if value is not None and value > 0 and value not in strikes:
                    strikes.append(value)

    total = fields.get("borehole_depth_m")
    if total is None and intervals:
        total = max(iv.bottom_m for iv in intervals)

    log = DrillingLog(
        site=site,
        borehole_ref=str(fields.get("borehole_ref", "") or ""),
        total_depth_m=total,
        drilling_method=fields.get("drilling_method", ""),
        intervals=sorted(intervals, key=lambda iv: iv.top_m),
        water_strikes_m=sorted(strikes),
        grouting_depth_m=fields.get("grouting_depth_m"),
        start_date=str(fields.get("start_date", "")),
        completion_date=str(fields.get("completion_date", "")),
        status=fields.get("status", ""),
        source=str(source),
    )

    # consistency of the interval column
    for a, b in zip(log.intervals, log.intervals[1:]):
        if b.top_m < a.bottom_m - 1e-9:
            flags.append(
                DataFlag(
                    "warning",
                    "interval_overlap",
                    f"Depth intervals overlap at {b.top_m} m.",
                )
            )
        elif b.top_m > a.bottom_m + 1e-9:
            flags.append(
                DataFlag(
                    "warning",
                    "interval_gap",
                    f"Gap in the drilling log between {a.bottom_m} m and {b.top_m} m.",
                )
            )
    if total and log.intervals and abs(log.intervals[-1].bottom_m - total) > 1e-6:
        flags.append(
            DataFlag(
                "warning",
                "depth_mismatch",
                f"Stated total depth {total} m differs from the deepest logged "
                f"interval {log.intervals[-1].bottom_m} m.",
            )
        )
    if not log.intervals:
        flags.append(
            DataFlag("error", "no_intervals", "No depth intervals found in the log.")
        )
    missing_desc = sum(1 for iv in log.intervals if not iv.description)
    if log.intervals and missing_desc:
        flags.append(
            DataFlag(
                "info",
                "missing_lithology",
                f"{missing_desc} interval(s) have no lithology description.",
            )
        )
    log.flags = flags
    return log
