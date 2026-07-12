"""Parsers for pumping test field sheets (Excel template and Word sheets).

The paper layout (WiNGiN step test sheet) records readings in side by
side hourly column groups, each with Time (min), Water Level (m) and
Drawdown (m), followed by a Recovery block. Two rules from the sheets
drive the parsing:

* The recorded drawdown column is the increment between successive
  readings, not drawdown below static. Only time and water level are
  read; true drawdown is always recomputed as water level minus static
  water level.
* Discharge is often missing. The test still parses and produces water
  level and drawdown series, but a ``missing_discharge`` flag marks all
  transmissivity and yield results as pending.

Times within each group are irregular (1, 2, 3 and 5 minute spacing);
nothing assumes uniform sampling.

Two recovery layouts occur on real sheets and both are handled:

* A dedicated recovery group with its own Time, Water Level and
  Recovery columns (Kuntolo sheet). Water level is read; the recovery
  increment column is ignored.
* A single shared time column with a Recovery column holding water
  levels during recovery (Dr. Timbo sheet). The recovery column is
  read against the shared times, interpreted as minutes since the pump
  stopped.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ..models import DataFlag, PumpingStep, PumpingTest
from ..utils import clean_text, parse_number
from . import common

_DISCHARGE_TEXT_RE = re.compile(
    r"discharge\s*(?:of|0f)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*m3?\s*/?\s*h", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Locating the column groups
# ---------------------------------------------------------------------------

def _find_groups(grid: list[list]) -> tuple[int, list[dict]] | None:
    """Find the header row of Time / Water Level / ... column groups.

    Returns ``(row_index, groups)``. Each group has column indices and
    ``kind`` of "pumping" or "recovery". A "reco" column adjacent to a
    time column forms a recovery triplet (level read from its own water
    level column); a distant "reco" column shares the pumping time
    column and holds water levels itself.
    """
    best: tuple[int, list[dict]] | None = None
    for r, row in enumerate(grid):
        texts = common.row_text(row)
        time_cols = [c for c, t in enumerate(texts) if t.startswith("time")]
        if not time_cols:
            continue
        groups: list[dict] = []
        for gi, c in enumerate(time_cols):
            end = time_cols[gi + 1] if gi + 1 < len(time_cols) else len(texts)
            level_col = None
            reco_col = None
            for cc in range(c + 1, end):
                t = texts[cc]
                if not t:
                    continue
                if ("water" in t or t.startswith("level")) and level_col is None:
                    level_col = cc
                elif "reco" in t and reco_col is None:
                    reco_col = cc
            if level_col is None and reco_col is None:
                continue
            if reco_col is not None and level_col is not None:
                if reco_col - c <= 2:
                    # Kuntolo style triplet: Time, Water Level, Recovery increment
                    groups.append({"time": c, "level": level_col, "kind": "recovery"})
                else:
                    # Dr. Timbo style: shared time column; recovery column holds levels
                    groups.append({"time": c, "level": level_col, "kind": "pumping"})
                    groups.append({"time": c, "level": reco_col, "kind": "recovery"})
            elif reco_col is not None:
                groups.append({"time": c, "level": reco_col, "kind": "recovery"})
            else:
                groups.append({"time": c, "level": level_col, "kind": "pumping"})
        if groups and (best is None or len(groups) > len(best[1])):
            best = (r, groups)
    return best


def _read_series(grid: list[list], header_row: int, group: dict) -> tuple[np.ndarray, np.ndarray]:
    times, levels = [], []
    for row in grid[header_row + 1 :]:
        t = parse_number(row[group["time"]]) if group["time"] < len(row) else None
        wl = parse_number(row[group["level"]]) if group["level"] < len(row) else None
        if t is None or wl is None:
            continue
        times.append(t)
        levels.append(wl)
    return np.array(times, dtype=float), np.array(levels, dtype=float)


def _find_step_discharges(grid: list[list]) -> dict[int, float]:
    """Read per step discharge from 'Step n Q' labelled cells."""
    discharges: dict[int, float] = {}
    for row in grid:
        for c, cell in enumerate(row):
            text = clean_text(cell).lower()
            if text.startswith("step") and "q" in text:
                num = parse_number(text.split("q")[0])
                if num is None:
                    continue
                for cc in range(c + 1, min(c + 3, len(row))):
                    val = parse_number(row[cc])
                    if val is not None:
                        discharges[int(num)] = val
                        break
    return discharges


def _discharge_candidates_from_text(grid: list[list]) -> list[float]:
    """Discharge values mentioned in free text such as
    'Constant Discharge of 2.93m3/h'."""
    found: list[float] = []
    for row in grid:
        for cell in row:
            if cell is None or isinstance(cell, (int, float)):
                continue
            for m in _DISCHARGE_TEXT_RE.finditer(str(cell)):
                value = float(m.group(1))
                if value not in found:
                    found.append(value)
    return found


def _sheet_test_type(grid: list[list]) -> str:
    """Look for 'STEP TEST' or 'CONSTANT DISCHARGE' banners in the sheet."""
    for row in grid:
        for cell in row:
            text = clean_text(cell).lower()
            if not text:
                continue
            if "step test" in text or "step drawdown" in text:
                return "step"
            if "constant discharge" in text or "constant rate" in text:
                return "constant"
    return ""


# ---------------------------------------------------------------------------
# Assembling the PumpingTest
# ---------------------------------------------------------------------------

def _assemble(grid: list[list], source: str) -> PumpingTest:
    fields = common.extract_header_fields(grid, max_rows=len(grid))
    site = common.site_from_fields(fields, source=source)
    flags: list[DataFlag] = []

    located = _find_groups(grid)
    if located is None:
        raise ValueError(f"No Time/Water Level column groups found in {source}")
    header_row, groups = located

    pumping_series = [
        _read_series(grid, header_row, g) for g in groups if g["kind"] == "pumping"
    ]
    pumping_series = [(t, wl) for t, wl in pumping_series if len(t)]
    recovery_series = [
        _read_series(grid, header_row, g) for g in groups if g["kind"] == "recovery"
    ]
    recovery_series = [(t, wl) for t, wl in recovery_series if len(t)]

    test_type = str(fields.get("test_type", "")).strip().lower()
    if not test_type:
        test_type = _sheet_test_type(grid)
    if not test_type:
        test_type = "step" if len(pumping_series) > 1 else "constant"

    if test_type.startswith("constant") and len(pumping_series) > 1:
        # hourly column groups are one continuous series on constant tests
        t = np.concatenate([s[0] for s in pumping_series])
        wl = np.concatenate([s[1] for s in pumping_series])
        order = np.argsort(t, kind="stable")
        pumping_series = [(t[order], wl[order])]

    step_length = fields.get("step_length_min")
    discharges = _find_step_discharges(grid)

    steps: list[PumpingStep] = []
    for i, (t, wl) in enumerate(pumping_series, start=1):
        steps.append(
            PumpingStep(
                step_number=i,
                time_min=t,
                water_level_m=wl,
                discharge_m3_per_h=discharges.get(i),
                label=f"Step {i}" if len(pumping_series) > 1 else "Pumping phase",
            )
        )

    # Free-text discharge: use it only when unambiguous (one candidate, one step)
    candidates = _discharge_candidates_from_text(grid)
    missing = [s for s in steps if s.discharge_m3_per_h is None]
    if candidates and missing:
        if len(candidates) == 1 and len(steps) == 1:
            steps[0].discharge_m3_per_h = candidates[0]
            flags.append(
                DataFlag(
                    "info",
                    "discharge_from_text",
                    f"Discharge {candidates[0]} m3/h taken from a text note on the "
                    "sheet; confirm against the measured value.",
                )
            )
        else:
            flags.append(
                DataFlag(
                    "warning",
                    "discharge_ambiguous",
                    "Discharge mentioned in sheet text ("
                    + ", ".join(f"{c} m3/h" for c in candidates)
                    + ") but not assigned per step; enter values in the template.",
                )
            )

    recovery_time = recovery_level = None
    if recovery_series:
        recovery_time, recovery_level = recovery_series[0]

    if recovery_time is not None:
        test_type += "+recovery"

    swl = fields.get("static_water_level_m")
    pumping_duration = None
    if steps:
        pumping_duration = float(max(s.time_min.max() for s in steps))

    test = PumpingTest(
        site=site,
        borehole_ref=str(fields.get("borehole_ref", "") or ""),
        test_type=test_type,
        static_water_level_m=swl,
        borehole_depth_m=fields.get("borehole_depth_m"),
        pump_setting_m=fields.get("pump_setting_m"),
        step_length_min=step_length,
        steps=steps,
        recovery_time_min=recovery_time,
        recovery_level_m=recovery_level,
        pumping_duration_min=pumping_duration,
        source=str(source),
    )

    # ---- data quality flags ------------------------------------------------
    if swl is None:
        flags.append(
            DataFlag(
                "error",
                "missing_static_water_level",
                "Static water level is missing; drawdown cannot be computed.",
            )
        )
    missing_q = [s.step_number for s in steps if s.discharge_m3_per_h is None]
    if missing_q:
        flags.append(
            DataFlag(
                "warning",
                "missing_discharge",
                "Discharge not recorded for step(s) "
                + ", ".join(str(n) for n in missing_q)
                + ". Drawdown and recovery curves are produced, but transmissivity "
                "and yield results are pending until discharge values are supplied.",
            )
        )
    if swl is not None and steps:
        if any(np.any(s.water_level_m < swl - 0.01) for s in steps):
            flags.append(
                DataFlag(
                    "warning",
                    "water_level_above_static",
                    "Some pumping water levels are above the stated static water "
                    "level, giving negative drawdown. Check the static level and "
                    "the measuring datum on the sheet.",
                )
            )
    for s in steps:
        if np.any(np.diff(s.time_min) <= 0):
            flags.append(
                DataFlag(
                    "warning",
                    "time_not_increasing",
                    f"Times are not strictly increasing in {s.label}.",
                    s.label,
                )
            )
    if test.borehole_depth_m and test.pump_setting_m:
        if test.pump_setting_m > test.borehole_depth_m:
            flags.append(
                DataFlag(
                    "warning",
                    "pump_below_borehole",
                    "Pump setting is deeper than the borehole depth.",
                )
            )
    if test.borehole_depth_m and steps:
        max_wl = max(float(np.nanmax(s.water_level_m)) for s in steps)
        if max_wl > test.borehole_depth_m:
            flags.append(
                DataFlag(
                    "warning",
                    "level_below_borehole",
                    f"Recorded water level {max_wl:.2f} m exceeds the stated "
                    f"borehole depth {test.borehole_depth_m:.0f} m; check the sheet.",
                )
            )
    test.flags = flags
    return test


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def read_pumping_workbook(path: str | Path) -> PumpingTest:
    """Read a pumping test from the Excel template layout."""
    grid, _ = common.load_grid(path)
    return _assemble(grid, source=str(path))


def read_pumping_docx(path: str | Path) -> PumpingTest:
    """Read a pumping test from a Word field sheet (Kuntolo style).

    Paragraph text supplies the header block; the table whose header
    contains Time / Water Level column groups supplies the readings.
    """
    import docx  # python-docx

    path = Path(path)
    document = docx.Document(str(path))

    header_grid: list[list] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        parts = [p for p in re.split(r"\t+|\s{3,}", text) if p.strip()]
        header_grid.append(parts)

    best_table: list[list] | None = None
    best_count = 0
    for table in document.tables:
        grid = [[cell.text for cell in row.cells] for row in table.rows]
        located = _find_groups(grid)
        if located and len(located[1]) > best_count:
            best_table = grid
            best_count = len(located[1])
    if best_table is None:
        raise ValueError(f"No pumping test table found in {path}")

    return _assemble(header_grid + best_table, source=str(path))
